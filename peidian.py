#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配电箱系统图自动生成器 v0.1
输入：设备清单(CSV/xlsx) -> 负荷计算 -> 自动回路划分 -> 国标配电箱系统图(SVG)

设计依据（简化版，工程使用前请复核 GB 50054 / GB 51348）：
  - 单相 220V，功率因数取 0.9
  - 导线载流量按铜芯 BV 穿管暗敷、环境 30℃ 保守取值
  - 断路器按 C 型微型断路器（居民配电常用）
  - 插座 / 厨房 / 卫生间回路带剩余电流保护(RCD)

零依赖：标准库即可运行；若装有 openpyxl 可直接读 .xlsx。
"""
import csv
import os
import sys
import argparse

# ---------------- 常量 ----------------
U = 220.0            # 单相电压 (V)
COS_PHI = 0.9        # 默认功率因数
KX_TOTAL = 0.85      # 总同时系数（住宅经验值）

# 导线载流量 (铜芯 BV 穿管/暗敷, 30℃, 保守取值 A)
WIRE_TABLE = [
    (1.5, 16), (2.5, 20), (4.0, 25), (6.0, 32),
    (10.0, 44), (16.0, 60), (25.0, 85), (35.0, 105), (50.0, 130),
]
# C 型微型断路器额定序列 (A)
BREAKER_SERIES = [6, 10, 16, 20, 25, 32, 40, 50, 63, 80, 100]
# 需要系数（多台设备时取值；单台取 1.0）
KX_BY_TYPE = {
    '照明': 0.8, '插座': 0.7, '空调': 0.9, '厨房': 0.9, '卫生间': 0.8, '大功率': 1.0
}
# 带剩余电流保护(RCD)的回路类型
RCD_TYPES = {'插座', '厨房', '卫生间'}


# ---------------- 数据读取 ----------------
def read_devices(path):
    """读取设备清单，支持 CSV / xlsx（需 openpyxl）。"""
    devices = []
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xlsx', '.xlsm'):
        try:
            import openpyxl
        except ImportError:
            print('[警告] 未安装 openpyxl，无法读取 xlsx，请转为 CSV 或使用 --demo')
            sys.exit(1)
        wb = openpyxl.load_workbook(path, data_only=True)
        ws = wb.active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        header = [str(c).strip() if c is not None else '' for c in rows[0]]
        idx = {h: i for i, h in enumerate(header)}
        colmap = [
            (('房间', 'room'), ('设备', '设备名称', 'name'),
             ('类型', 'type'), ('功率', '功率W', 'power'), ('数量', 'qty')),
        ]
        for r in rows[1:]:
            if r is None or all(c is None for c in r):
                continue
            room = _cell(r, idx, '房间', 'room')
            name = _cell(r, idx, '设备', '设备名称', 'name')
            typ = _cell(r, idx, '类型', 'type')
            power = _cell(r, idx, '功率', '功率W', 'power')
            qty = _cell(r, idx, '数量', 'qty') or 1
            if not name or not typ or power in (None, ''):
                continue
            devices.append(_mk_device(room, name, typ, power, qty))
    else:
        with open(path, encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for r in reader:
                room = r.get('房间') or r.get('room') or ''
                name = r.get('设备') or r.get('设备名称') or r.get('name') or ''
                typ = r.get('类型') or r.get('type') or ''
                power = r.get('功率') or r.get('功率W') or r.get('power') or ''
                qty = r.get('数量') or r.get('qty') or 1
                if not name or not typ or not power:
                    continue
                devices.append(_mk_device(room, name, typ, power, qty))
    return devices


def _cell(row, idx, *names):
    for n in names:
        if n in idx:
            return row[idx[n]]
    return None


def _mk_device(room, name, typ, power, qty):
    return {
        'room': str(room).strip(),
        'name': str(name).strip(),
        'type': str(typ).strip(),
        'power': float(str(power).strip()),
        'qty': int(float(str(qty).strip() or 1)),
    }


# ---------------- 负荷计算 ----------------
def circuit_calc(devices, typ):
    total = sum(d['power'] * d['qty'] for d in devices)
    n = sum(d['qty'] for d in devices)
    kx = 1.0 if n <= 1 else KX_BY_TYPE.get(typ, 0.8)
    Ijs = total * kx / (U * COS_PHI)
    return total, n, kx, Ijs


def select_protection(Ijs, min_area=2.5):
    """按计算电流选断路器与导线。In >= Ijs 且 导线载流量 >= In 且 截面 >= min_area。"""
    In = next((b for b in BREAKER_SERIES if b >= Ijs), BREAKER_SERIES[-1])
    chosen = None
    for a, c in WIRE_TABLE:
        if c >= In and a >= min_area:
            chosen = (a, c)
            break
    if chosen is None:                 # 极端情况，取最大线径兜底
        a, c = WIRE_TABLE[-1]
        In = max(In, BREAKER_SERIES[-1])
        return In, a, c
    return In, chosen[0], chosen[1]


def make_circuit(devices, typ, force_rcd=False):
    total, n, kx, Ijs = circuit_calc(devices, typ)
    # 最小线径：住宅固定布线一般不低于 2.5mm²；柜机/大功率宜 4mm²
    min_area = 2.5
    if typ == '空调' and total >= 3000:
        min_area = 4.0
    if typ in ('大功率', '厨房'):
        min_area = 4.0
    In, area, wcur = select_protection(Ijs, min_area)
    rcd = force_rcd or (typ in RCD_TYPES)
    rooms = '+'.join(sorted(set(d['room'] for d in devices if d['room'])))
    label = ','.join(f'{d["name"]}×{d["qty"]}' for d in devices)
    return {
        'type': typ, 'devices': devices, 'total': total, 'n': n,
        'kx': kx, 'Ijs': Ijs, 'In': In, 'area': area, 'wcur': wcur,
        'rcd': rcd, 'rooms': rooms, 'label': label,
    }


def split_by_power(devices, typ, limit):
    """按累计功率切分回路，单回路总功率不超过 limit(W)。"""
    out, cur, cur_p = [], [], 0
    for d in devices:
        p = d['power'] * d['qty']
        if cur and cur_p + p > limit:
            out.append(make_circuit(cur, typ))
            cur, cur_p = [], 0
        cur.append(d)
        cur_p += p
    if cur:
        out.append(make_circuit(cur, typ))
    return out


def group_sockets(sockets):
    """普通插座按房间聚合，每回路插座数 <=10 且功率 <=2200W。"""
    by_room = {}
    for d in sockets:
        by_room.setdefault(d['room'] or '其他', []).append(d)
    circuits, buf, buf_p, buf_q = [], [], 0, 0

    def flush():
        nonlocal buf, buf_p, buf_q
        if buf:
            circuits.append(make_circuit(buf, '插座'))
            buf, buf_p, buf_q = [], 0, 0

    for room, devs in by_room.items():
        for d in devs:
            p = d['power'] * d['qty']
            if buf_q + d['qty'] > 10 or buf_p + p > 2200:
                flush()
            buf.append(d)
            buf_p += p
            buf_q += d['qty']
    flush()
    return circuits


def build_circuits(devices):
    circuits = []
    lights = [d for d in devices if d['type'] == '照明']
    circuits += split_by_power(lights, '照明', 2000)
    for d in [x for x in devices if x['type'] == '空调']:
        circuits.append(make_circuit([d], '空调'))
    kit = [d for d in devices if d['type'] == '厨房']
    circuits += split_by_power(kit, '厨房', 6000)
    for d in [x for x in devices if x['type'] == '大功率' and '卫生间' not in x['room']]:
        circuits.append(make_circuit([d], '大功率'))
    bath_other = [d for d in devices if d['type'] == '卫生间']
    circuits += split_by_power(bath_other, '卫生间', 2000)
    bath_power = [d for d in devices if d['type'] == '大功率' and '卫生间' in d['room']]
    for d in bath_power:
        circuits.append(make_circuit([d], '大功率', force_rcd=True))
    sockets = [d for d in devices if d['type'] == '插座']
    circuits += group_sockets(sockets)
    return circuits


def main_feed(circuits):
    P_total = sum(c['total'] for c in circuits)
    I_total = sum(c['Ijs'] for c in circuits) * KX_TOTAL
    In, area, wcur = select_protection(I_total)
    return {'P_total': P_total, 'I_total': I_total, 'In': In, 'area': area}


# ---------------- 出图 (SVG) ----------------
def gen_svg(circuits, main_info, title='配电箱系统图'):
    row_h = 64
    top = 100
    left_bus = 160
    n = len(circuits)
    height = top + n * row_h + 70
    width = 1000
    p = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'font-family="Microsoft YaHei, SimHei, sans-serif">')
    p.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    p.append(f'<text x="40" y="40" font-size="22" font-weight="bold">{title}</text>')
    p.append(f'<text x="40" y="64" font-size="13" fill="#555">总进线 单相220V ｜ 总开关 C{main_info["In"]} ｜ '
             f'进线 BV-{main_info["area"]} ｜ 总负荷 {main_info["P_total"]/1000:.2f} kW ｜ '
             f'计算电流 {main_info["I_total"]:.1f} A</text>')

    # 进线
    p.append(f'<text x="40" y="{top-22}" font-size="13">220V</text>')
    # 总开关
    sw_x, sw_y, sw_w, sw_h = 100, top - 44, 56, 36
    p.append(f'<rect x="{sw_x}" y="{sw_y}" width="{sw_w}" height="{sw_h}" fill="#e8f0ff" stroke="#333"/>')
    p.append(f'<text x="{sw_x+sw_w/2}" y="{sw_y+sw_h/2+5}" font-size="13" text-anchor="middle">C{main_info["In"]}</text>')
    # 母线
    bus_top = sw_y + sw_h
    bus_bottom = top + n * row_h - 10
    p.append(f'<line x1="{left_bus}" y1="{bus_top}" x2="{left_bus}" y2="{bus_bottom}" stroke="#333" stroke-width="4"/>')

    for i, c in enumerate(circuits):
        y = top + i * row_h + 22
        p.append(f'<line x1="{left_bus}" y1="{y}" x2="{left_bus+120}" y2="{y}" stroke="#333" stroke-width="2"/>')
        bx, by, bw, bh = left_bus + 120, y - 13, 46, 26
        fill = '#ffecec' if c['rcd'] else '#e8f0ff'
        stroke = '#c33' if c['rcd'] else '#36c'
        p.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="{fill}" stroke="{stroke}"/>')
        p.append(f'<text x="{bx+bw/2}" y="{by+18}" font-size="12" text-anchor="middle" fill="{stroke}">C{c["In"]}</text>')
        label = f'W{i+1} {c["type"]}回路'
        if c['rooms']:
            label += f'（{c["rooms"]}）'
        p.append(f'<text x="{bx+bw+12}" y="{y-4}" font-size="13">{label}</text>')
        p.append(f'<text x="{bx+bw+12}" y="{y+14}" font-size="12" fill="#444">'
                 f'BV-{c["area"]} ｜ Ijs={c["Ijs"]:.1f}A ｜ 负荷 {c["total"]/1000:.2f}kW'
                 f'{" ｜ [RCD]" if c["rcd"] else ""}</text>')
        # 末端导线
        p.append(f'<line x1="{left_bus+120}" y1="{y}" x2="{width-40}" y2="{y}" stroke="#999" stroke-width="1" stroke-dasharray="4 3"/>')
    p.append('</svg>')
    return '\n'.join(p)


def gen_report(circuits, main_info):
    lines = []
    lines.append('# 配电负荷计算书\n')
    lines.append(f'- 总设备功率：{main_info["P_total"]/1000:.2f} kW')
    lines.append(f'- 总同时系数：{KX_TOTAL}')
    lines.append(f'- 计算总电流：{main_info["I_total"]:.1f} A')
    lines.append(f'- 总开关：C{main_info["In"]}（2P） ｜ 进线：BV-{main_info["area"]}\n')
    lines.append('| 回路 | 类型 | 区域 | 设备明细 | 功率(kW) | 需要系数 | 计算电流(A) | 导线 | 断路器 | 漏保 |')
    lines.append('|---|---|---|---|---|---|---|---|---|---|')
    for i, c in enumerate(circuits):
        lines.append(
            f'| W{i+1} | {c["type"]} | {c["rooms"]} | {c["label"]} | '
            f'{c["total"]/1000:.2f} | {c["kx"]:.2f} | {c["Ijs"]:.1f} | '
            f'BV-{c["area"]} | C{c["In"]} | {"是" if c["rcd"] else "否"} |'
        )
    return '\n'.join(lines)


# ---------------- 示例数据 ----------------
def DEMO_DEVICES():
    rows = [
        ('客厅', 'LED主灯', '照明', 80, 1), ('客厅', '灯带', '照明', 40, 1),
        ('客厅', '电视', '插座', 200, 1), ('客厅', '空调柜机', '空调', 3500, 1),
        ('客厅', '扫地机器人', '插座', 50, 1),
        ('餐厅', '吊灯', '照明', 60, 1), ('餐厅', '冰箱', '插座', 150, 1),
        ('主卧', '吸顶灯', '照明', 50, 1), ('主卧', '空调挂机', '空调', 1500, 1),
        ('主卧', '电脑', '插座', 300, 1),
        ('次卧', '吸顶灯', '照明', 40, 1), ('次卧', '空调挂机', '空调', 1200, 1),
        ('次卧', '电脑', '插座', 200, 1),
        ('厨房', '吸顶灯', '照明', 40, 1), ('厨房', '抽油烟机', '厨房', 200, 1),
        ('厨房', '电磁炉', '厨房', 2100, 1), ('厨房', '微波炉', '厨房', 1000, 1),
        ('厨房', '电饭煲', '厨房', 800, 1), ('厨房', '净水器', '插座', 50, 1),
        ('卫生间1', '浴霸', '卫生间', 1100, 1), ('卫生间1', '热水器', '大功率', 2500, 1),
        ('卫生间1', '排气扇', '插座', 40, 1),
        ('卫生间2', '浴霸', '卫生间', 1100, 1), ('卫生间2', '排气扇', '插座', 40, 1),
        ('阳台', '洗衣机', '插座', 500, 1), ('阳台', '晾衣架', '插座', 40, 1),
    ]
    return [_mk_device(r, n, t, p, q) for (r, n, t, p, q) in rows]


# ---------------- 入口 ----------------
def main():
    ap = argparse.ArgumentParser(description='配电箱系统图自动生成器')
    ap.add_argument('input', nargs='?', help='设备清单 CSV/xlsx')
    ap.add_argument('--demo', action='store_true', help='使用示例数据')
    ap.add_argument('--out', default=None, help='输出目录')
    args = ap.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))
    out_dir = args.out or os.path.join(base, 'output')
    os.makedirs(out_dir, exist_ok=True)

    if args.demo or not args.input:
        devices = DEMO_DEVICES()
        print('[信息] 使用示例数据（120㎡ 住宅）')
    else:
        devices = read_devices(args.input)
        print(f'[信息] 读取设备 {len(devices)} 项：{args.input}')

    circuits = build_circuits(devices)
    main_info = main_feed(circuits)

    svg = gen_svg(circuits, main_info)
    svg_path = os.path.join(out_dir, '配电系统图.svg')
    with open(svg_path, 'w', encoding='utf-8') as f:
        f.write(svg)

    rep = gen_report(circuits, main_info)
    rep_path = os.path.join(out_dir, '负荷计算书.md')
    with open(rep_path, 'w', encoding='utf-8') as f:
        f.write(rep)

    print(f'已生成：{svg_path}')
    print(f'已生成：{rep_path}')
    print(f'共 {len(circuits)} 个回路，总负荷 {main_info["P_total"]/1000:.2f} kW，'
          f'总开关 C{main_info["In"]}，进线 BV-{main_info["area"]}')


if __name__ == '__main__':
    main()
