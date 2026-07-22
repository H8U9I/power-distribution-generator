# -*- coding: utf-8 -*-
"""
配电箱系统图计算引擎
- 单相(220V) / 三相(380V) 负荷计算
- 三相平衡分配 (贪心算法，把单相回路分配到电流最小的相)
- 线缆选型 (含防火降容、最小线径约束)
- 断路器 (C型微断) 选型
- RCD(漏电保护) 规则
参照 GB 50054 / GB 51348 简化算法，仅作辅助设计，正式施工图须专业校核。
"""

import math

# ---------------------------------------------------------------------------
# 标准数据表
# ---------------------------------------------------------------------------

# BV 铜芯聚氯乙烯绝缘导线，穿管敷设(~30℃)，单/三相载流量参考(A)
# (标称截面 mm², 载流量 A)
WIRE_TABLE = [
    (1.5, 16), (2.5, 25), (4.0, 32), (6.0, 40), (10.0, 55),
    (16.0, 75), (25.0, 100), (35.0, 120), (50.0, 150),
    (70.0, 190), (95.0, 230), (120.0, 280), (150.0, 320),
]

# C型微型断路器额定值序列 (A)
BREAKER_SERIES = [6, 10, 13, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125, 160, 200, 250]

# 防火等级 -> 线缆前缀 + 降容系数
FIRE_RATINGS = {
    "普通":     {"prefix": "",     "derate": 1.00, "desc": "普通型，无特殊防火要求"},
    "阻燃C级":  {"prefix": "ZC-",  "derate": 0.90, "desc": "ZC 阻燃，载流量约×0.9"},
    "阻燃B级":  {"prefix": "ZB-",  "derate": 0.90, "desc": "ZB 阻燃，载流量约×0.9"},
    "耐火":     {"prefix": "NH-",  "derate": 0.85, "desc": "NH 耐火，载流量约×0.85"},
    "低烟无卤": {"prefix": "WDZ-", "derate": 0.85, "desc": "WDZ 低烟无卤阻燃，载流量约×0.85"},
}

# 线缆基型
CABLE_TYPES = {
    "BV":  {"desc": "铜芯聚氯乙烯绝缘硬线(单芯)", "min_area": 1.5},
    "BVR": {"desc": "铜芯聚氯乙烯绝缘软线", "min_area": 1.5},
    "YJV": {"desc": "交联聚乙烯绝缘电力电缆(三相/大电流)", "min_area": 1.5},
    "NH-BV": {"desc": "耐火铜芯聚氯乙烯绝缘线", "min_area": 1.5},
}

# 各回路类型默认参数
# min_breaker: 该类回路空开额定值下限(贴近实际安装习惯)
CATEGORY_DEFAULTS = {
    "socket":   {"kx": 0.6, "cosphi": 0.9, "min_area": 2.5, "min_breaker": 16, "rcd": True,  "label": "插座"},
    "lighting": {"kx": 0.9, "cosphi": 0.9, "min_area": 2.5, "min_breaker": 10, "rcd": False, "label": "照明"},
    "device":   {"kx": 1.0, "cosphi": 0.9, "min_area": 2.5, "min_breaker": 6,  "rcd": False, "label": "设备"},
}

# 单相常用插座每插座估算负荷 (W)，用于仅有数量无设备时的估算
SOCKET_EST_W = 200

# 三相设备功率阈值(单相设备超过此值建议走三相，仅提示)
THREE_PHASE_HINT_W = 3000

# 含较大启动电流的设备类型 -> 该类回路空开下限上浮(仍按功率匹配，仅对电机类合理上浮)
MOTOR_TYPES = {"空调", "柜机", "挂机", "水泵", "电机", "压缩机", "新风", "排风扇", "油烟机"}


# ---------------------------------------------------------------------------
# 选型核心函数
# ---------------------------------------------------------------------------

def next_breaker(current):
    """取 >= current 的最小标准断路器额定值。"""
    for b in BREAKER_SERIES:
        if b >= current:
            return b
    return BREAKER_SERIES[-1]


def select_wire(in_breaker, fire_rating, min_area=2.5):
    """按断路器额定电流选导线截面(考虑防火降容与最小线径)。"""
    derate = FIRE_RATINGS.get(fire_rating, FIRE_RATINGS["普通"])["derate"]
    need = in_breaker / derate
    chosen = None
    for area, amp in WIRE_TABLE:
        if area < min_area:
            continue
        if amp >= need:
            chosen = (area, amp)
            break
    if chosen is None:
        chosen = WIRE_TABLE[-1]
    return chosen


def cable_full_name(area, cable_type, fire_rating):
    """生成如 'ZC-BV-2.5' 的线缆标注。"""
    prefix = FIRE_RATINGS.get(fire_rating, FIRE_RATINGS["普通"])["prefix"]
    return f"{prefix}{cable_type}-{area:g}"


# ---------------------------------------------------------------------------
# 单回路(分路)计算
# ---------------------------------------------------------------------------

def calc_subloop_current(sl):
    """
    计算一个分路的计算电流 Ijs (A) 与总有功功率 (W)。
    sl: dict {devices:[...], kx?, cosphi?, threePhase?, est_load_w?}
    """
    devices = sl.get("devices", []) or []
    total_p = sl.get("est_load_w", 0) or 0  # 估算负荷(常用插座按数量算)
    for d in devices:
        qty = d.get("qty", 1) or 1
        total_p += (d.get("power", 0) or 0) * qty

    three_phase = sl.get("threePhase", False) or any(d.get("threePhase") for d in devices)

    defaults = CATEGORY_DEFAULTS.get(sl.get("category", "device"), CATEGORY_DEFAULTS["device"])

    # 需用系数 kx
    if sl.get("kx") not in (None, ""):
        kx = float(sl["kx"])
    elif devices:
        wsum = sum((d.get("power", 0) or 0) * (d.get("qty", 1) or 1) for d in devices)
        kx = sum((d.get("kx") or defaults["kx"]) * (d.get("power", 0) or 0) * (d.get("qty", 1) or 1)
                 for d in devices) / wsum if wsum else defaults["kx"]
    else:
        kx = defaults["kx"]

    # 功率因数
    if sl.get("cosphi") not in (None, ""):
        cosphi = float(sl["cosphi"])
    elif devices:
        wsum = sum((d.get("power", 0) or 0) * (d.get("qty", 1) or 1) for d in devices)
        cosphi = sum((d.get("cosphi") or defaults["cosphi"]) * (d.get("power", 0) or 0) * (d.get("qty", 1) or 1)
                     for d in devices) / wsum if wsum else defaults["cosphi"]
    else:
        cosphi = defaults["cosphi"]

    cosphi = max(0.5, min(1.0, cosphi))
    kx = max(0.1, min(1.0, kx))

    if three_phase:
        I = total_p * kx / (math.sqrt(3) * 380.0 * cosphi) if total_p > 0 else 0.0
    else:
        I = total_p * kx / (220.0 * cosphi) if total_p > 0 else 0.0

    return {"total_p": total_p, "kx": kx, "cosphi": cosphi, "Ijs": I, "three_phase": three_phase}


def classify_subloop(sl):
    """判断该分路是否需要 RCD 及最小线径。"""
    cat = sl.get("category", "device")
    defaults = CATEGORY_DEFAULTS.get(cat, CATEGORY_DEFAULTS["device"])
    rcd = sl.get("rcd", defaults["rcd"])
    min_area = defaults["min_area"]
    for d in sl.get("devices", []) or []:
        room = (d.get("room") or "")
        typ = (d.get("type") or "")
        p = (d.get("power", 0) or 0) * (d.get("qty", 1) or 1)
        if any(k in room for k in ["卫生间", "厨房", "阳台", "浴室", "水"]) or \
           any(k in typ for k in ["热水", "浴霸", "水泵", "空调", "插座"]):
            rcd = True
        if p >= 3000 or typ in ("大功率", "热水器", "柜机"):
            min_area = max(min_area, 4.0)
    if sl.get("is_dedicated") and cat == "socket":
        rcd = True
    return rcd, min_area


# ---------------------------------------------------------------------------
# 项目级计算（三相平衡 + 总开关 + 进线）
# ---------------------------------------------------------------------------

def compute_project(project):
    """输入 project(dict)，输出计算结果 dict。"""
    meta = project.get("meta", {})
    v_system = meta.get("voltage_system", "three")
    fire_rating = meta.get("fire_rating", "普通")
    cable_type = meta.get("cable_type", "BV")

    # 1) 展平分路，计算每个分路
    circuits = []
    for g in project.get("groups", []):
        cat = g.get("category", "device")
        for sl in g.get("subloops", []):
            sl["category"] = cat
            cur = calc_subloop_current(sl)
            rcd, min_area = classify_subloop(sl)
            defaults = CATEGORY_DEFAULTS.get(cat, CATEGORY_DEFAULTS["device"])
            min_br = defaults["min_breaker"]
            # 电机类(空调等)启动电流大，空开下限上浮到 16A
            type_min = 0
            for d in sl.get("devices", []) or []:
                if (d.get("type") or "") in MOTOR_TYPES:
                    type_min = max(type_min, 16)
            In = max(next_breaker(cur["Ijs"]), min_br, type_min)
            area, wamp = select_wire(In, fire_rating, min_area)
            dev_names = []
            for d in sl.get("devices", []) or []:
                q = d.get("qty", 1) or 1
                nm = d.get("name", "设备")
                dev_names.append(f"{nm}×{q}" if q > 1 else nm)
            if sl.get("est_load_w"):
                dev_names.append(f"插座估算{sl['est_load_w']}W")
            circuits.append({
                "id": sl.get("id"),
                "group": g.get("name", cat),
                "category": cat,
                "name": sl.get("name", "回路"),
                "is_dedicated": sl.get("is_dedicated", False),
                "devices_text": "、".join(dev_names) if dev_names else "—",
                "total_p": cur["total_p"],
                "kx": round(cur["kx"], 2),
                "cosphi": round(cur["cosphi"], 2),
                "Ijs": round(cur["Ijs"], 2),
                "three_phase": cur["three_phase"],
                "In": In,
                "wire_area": area,
                "wire_amp": wamp,
                "rcd": rcd,
                "min_area": min_area,
            })

    # 2) 三相平衡分配
    phases = {"L1": 0.0, "L2": 0.0, "L3": 0.0}
    single = [c for c in circuits if not c["three_phase"]]
    triple = [c for c in circuits if c["three_phase"]]

    for c in triple:
        for k in phases:
            phases[k] += c["Ijs"]
        c["phase"] = "L1/L2/L3"

    for c in sorted(single, key=lambda x: -x["Ijs"]):
        pk = min(phases, key=phases.get)
        phases[pk] += c["Ijs"]
        c["phase"] = pk

    # 3) 总开关与进线
    if v_system == "three":
        I_phase_max = max(phases.values())
        I_phase_min = min(phases.values())
        imbalance = (I_phase_max - I_phase_min) / I_phase_max * 100 if I_phase_max > 0 else 0
        In_main = next_breaker(I_phase_max)
        main_area, _ = select_wire(In_main, fire_rating, 4.0)
        n_area = main_area
        pe_area = max([a for a, _ in WIRE_TABLE if a >= max(main_area / 2.0, 4.0)] + [4.0])
        balanced_I = sum(c["total_p"] * c["kx"] for c in circuits) / (math.sqrt(3) * 380 * 0.9) if circuits else 0
        main_info = {
            "In_main": In_main, "main_area": main_area,
            "phase_currents": {k: round(v, 2) for k, v in phases.items()},
            "imbalance_pct": round(imbalance, 1),
            "incoming": f"{cable_full_name(main_area, cable_type, fire_rating)}-5×{main_area:g} (L1/L2/L3/N/PE)",
            "balanced_I": round(balanced_I, 2),
        }
    else:
        I_total = sum(c["Ijs"] for c in circuits)
        In_main = next_breaker(I_total)
        main_area, _ = select_wire(In_main, fire_rating, 2.5)
        main_info = {
            "In_main": In_main, "main_area": main_area,
            "phase_currents": {"L": round(I_total, 2)},
            "imbalance_pct": 0.0,
            "incoming": f"{cable_full_name(main_area, cable_type, fire_rating)}-2×{main_area:g} + PE",
            "balanced_I": round(I_total, 2),
        }

    # 4) 汇总
    P_raw = sum(d.get("power", 0) * (d.get("qty", 1) or 1)
                for g in project.get("groups", [])
                for sl in g.get("subloops", [])
                for d in sl.get("devices", []))
    P_demand = sum(c["total_p"] * c["kx"] for c in circuits)

    return {
        "meta": meta,
        "v_system": v_system,
        "fire_rating": fire_rating,
        "cable_type": cable_type,
        "circuits": circuits,
        "main": main_info,
        "totals": {
            "P_raw_W": P_raw,
            "P_raw_kW": round(P_raw / 1000, 2),
            "P_demand_W": round(P_demand),
            "P_demand_kW": round(P_demand / 1000, 2),
            "loop_count": len(circuits),
            "three_phase_loops": len(triple),
            "single_loops": len(single),
        },
    }


# ---------------------------------------------------------------------------
# 演示项目（一套约 120㎡ 住宅，三相入户）
# ---------------------------------------------------------------------------

def demo_project():
    return {
        "meta": {
            "name": "示例·120㎡住宅三相入户",
            "voltage_system": "three",
            "fire_rating": "普通",
            "cable_type": "BV",
            "default_cosphi": 0.9,
            "default_kx": 0.8,
        },
        "groups": [
            {
                "id": "g_sock", "category": "socket", "name": "插座回路",
                "config": {"common_socket_count": 18, "common_socket_loops": 3},
                "subloops": [
                    {"id": "s1", "name": "常用插座-1", "category": "socket", "is_dedicated": False,
                     "est_load_w": 1200, "devices": []},
                    {"id": "s2", "name": "常用插座-2", "category": "socket", "is_dedicated": False,
                     "est_load_w": 1200, "devices": []},
                    {"id": "s3", "name": "常用插座-3", "category": "socket", "is_dedicated": False,
                     "est_load_w": 1200, "devices": []},
                    {"id": "sd1", "name": "冰箱专用", "category": "socket", "is_dedicated": True,
                     "devices": [{"name": "冰箱", "room": "厨房", "type": "插座", "power": 200, "qty": 1}]},
                    {"id": "sd2", "name": "厨房小家电", "category": "socket", "is_dedicated": True,
                     "devices": [{"name": "微波炉", "room": "厨房", "type": "插座", "power": 1100, "qty": 1},
                                 {"name": "电饭煲", "room": "厨房", "type": "插座", "power": 800, "qty": 1}]},
                ],
            },
            {
                "id": "g_light", "category": "lighting", "name": "照明回路",
                "config": {"light_loops": 2},
                "subloops": [
                    {"id": "l1", "name": "照明-客餐厅", "category": "lighting",
                     "devices": [{"name": "LED主灯", "room": "客厅", "type": "照明", "power": 80, "qty": 1},
                                 {"name": "灯带", "room": "餐厅", "type": "照明", "power": 40, "qty": 1}]},
                    {"id": "l2", "name": "照明-卧室", "category": "lighting",
                     "devices": [{"name": "卧室吸顶灯", "room": "主卧", "type": "照明", "power": 60, "qty": 2}]},
                ],
            },
            {
                "id": "g_dev", "category": "device", "name": "设备回路",
                "subloops": [
                    {"id": "d1", "name": "挂机空调-主卧", "category": "device",
                     "devices": [{"name": "1.5P挂机", "room": "主卧", "type": "空调", "power": 1100, "qty": 1}]},
                    {"id": "d2", "name": "挂机空调-次卧", "category": "device",
                     "devices": [{"name": "1.5P挂机", "room": "次卧", "type": "空调", "power": 1100, "qty": 1}]},
                    {"id": "d3", "name": "柜机空调-客厅", "category": "device",
                     "devices": [{"name": "3P柜机", "room": "客厅", "type": "柜机", "power": 2500, "qty": 1}]},
                    {"id": "d4", "name": "卫生间浴霸", "category": "device",
                     "devices": [{"name": "浴霸", "room": "卫生间", "type": "浴霸", "power": 1100, "qty": 1}]},
                    {"id": "d5", "name": "热水器", "category": "device",
                     "devices": [{"name": "电热水器", "room": "卫生间", "type": "热水器", "power": 2000, "qty": 1}]},
                ],
            },
        ],
    }


if __name__ == "__main__":
    import json
    res = compute_project(demo_project())
    print(json.dumps(res, ensure_ascii=False, indent=2))
