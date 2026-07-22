# -*- coding: utf-8 -*-
"""
出图模块：标准配电箱系统图
- build_layout(result) -> 统一的图形元素列表(与渲染器解耦)
- render_svg(result)    -> SVG 字符串(浏览器预览)
- export_dxf(result, path) -> 写出 DXF 文件(ezdxf)
"""

import datetime
import os
from engine import cable_full_name

C_BUS = "#d6336c"
C_LINE = "#1f2937"
C_BRK = "#1c7ed6"
C_TEXT = "#111827"
C_MUT = "#6b7280"
C_RCD = "#e8590c"


def build_layout(result):
    meta = result.get("meta", {})
    v = result.get("v_system", "three")
    circuits = result.get("circuits", [])
    main = result.get("main", {})
    fire = result.get("fire_rating", "普通")
    ctype = result.get("cable_type", "BV")

    margin = 40
    bus_x = 300
    row_h = 50
    n = len(circuits)

    if v == "three":
        bus_lines = [("L1", 0), ("L2", 7), ("L3", 14), ("N", 26), ("PE", 34)]
    else:
        bus_lines = [("L", 0), ("N", 12), ("PE", 20)]

    title_y = 34
    sub_y = 56
    main_box_y = 96
    main_box_h = 36
    bus_top = main_box_y + main_box_h + 8
    bus_bottom = bus_top + n * row_h + 10

    els = []

    els.append({"type": "text", "x": margin, "y": title_y, "s": meta.get("name", "配电箱系统图"),
                "size": 20, "anchor": "start", "bold": True, "color": C_TEXT})
    els.append({"type": "text", "x": margin, "y": sub_y,
                "s": f"配电箱系统图  |  系统:{'三相380V' if v=='three' else '单相220V'}  |  "
                     f"防火:{fire}  线缆:{ctype}  |  总负荷:{result['totals']['P_demand_kW']}kW",
                "size": 12, "anchor": "start", "color": C_MUT})
    els.append({"type": "text", "x": margin, "y": sub_y + 18,
                "s": f"总开关 C{main.get('In_main')}  进线 {main.get('incoming')}  "
                     f"三相不平衡 {main.get('imbalance_pct')}%  |  生成 {datetime.date.today().isoformat()}",
                "size": 11, "anchor": "start", "color": C_MUT})

    els.append({"type": "line", "x1": margin, "y1": main_box_y + main_box_h/2,
                "x2": bus_x - 95, "y2": main_box_y + main_box_h/2, "w": 2, "color": C_LINE})
    els.append({"type": "text", "x": margin, "y": main_box_y + main_box_h/2 - 6,
                "s": "进线", "size": 11, "anchor": "start", "color": C_MUT})
    els.append({"type": "text", "x": margin, "y": main_box_y + main_box_h/2 + 10,
                "s": main.get("incoming", ""), "size": 11, "anchor": "start", "color": C_BUS})

    mbw = 78
    mbx = bus_x - 95 - mbw
    els.append({"type": "rect", "x": mbx, "y": main_box_y, "w": mbw, "h": main_box_h,
                "stroke": C_BRK, "fill": "#e7f5ff", "w": 2})
    pole = "3P" if v == "three" else "1P"
    els.append({"type": "text", "x": mbx + mbw/2, "y": main_box_y + 16,
                "s": f"C{main.get('In_main')}", "size": 13, "anchor": "middle", "bold": True, "color": C_BRK})
    els.append({"type": "text", "x": mbx + mbw/2, "y": main_box_y + 30,
                "s": f"总开关 {pole}", "size": 11, "anchor": "middle", "color": C_MUT})

    for name, dx in bus_lines:
        els.append({"type": "line", "x1": bus_x + dx, "y1": bus_top, "x2": bus_x + dx,
                    "y2": bus_bottom, "w": 3 if name in ("L1", "L") else 2,
                    "color": C_BUS if name in ("L1", "L", "L2", "L3") else "#868e96"})
    els.append({"type": "line", "x1": mbx + mbw, "y1": main_box_y + main_box_h/2,
                "x2": bus_x, "y2": main_box_y + main_box_h/2, "w": 2, "color": C_LINE})
    for name, dx in bus_lines:
        els.append({"type": "text", "x": bus_x + dx, "y": bus_top - 6, "s": name,
                    "size": 10, "anchor": "middle", "color": C_BUS if name in ("L1", "L", "L2", "L3") else "#868e96"})

    brk_w = 70
    brk_h = 30
    brk_x = bus_x + 42
    for i, c in enumerate(circuits):
        ry = bus_top + i * row_h + row_h/2
        if c["three_phase"]:
            phase_dx_list = [0, 7, 14]
        else:
            p = c.get("phase", "L1")
            phase_dx_list = [dict(bus_lines).get(p, 0)]
        for dx in phase_dx_list:
            els.append({"type": "line", "x1": bus_x + dx, "y1": ry, "x2": brk_x, "y2": ry,
                        "w": 2, "color": C_LINE})
        if not c["three_phase"]:
            els.append({"type": "text", "x": bus_x - 8, "y": ry + 4, "s": c.get("phase", ""),
                        "size": 10, "anchor": "end", "color": C_BUS})
        else:
            els.append({"type": "text", "x": bus_x - 8, "y": ry + 4, "s": "3φ",
                        "size": 10, "anchor": "end", "color": C_BUS})

        els.append({"type": "rect", "x": brk_x, "y": ry - brk_h/2, "w": brk_w, "h": brk_h,
                    "stroke": C_RCD if c["rcd"] else C_BRK, "fill": "#fff", "w": 2})
        brk_label = f"C{c['In']}"
        if c["rcd"]:
            brk_label += "+RCD"
        els.append({"type": "text", "x": brk_x + brk_w/2, "y": ry + 5,
                    "s": brk_label, "size": 12, "anchor": "middle", "bold": True,
                    "color": C_RCD if c["rcd"] else C_BRK})

        tx = brk_x + brk_w + 16
        wire = cable_full_name(c["wire_area"], ctype, fire)
        pol = "3×" if c["three_phase"] else "2×"
        wire_spec = f"{wire}-{pol}{c['wire_area']:g}"
        if c["rcd"]:
            wire_spec += " + PE"
        line1 = f"{c['name']}   [{c['devices_text']}]"
        line2 = (f"P={c['total_p']}W  Ijs={c['Ijs']}A  kx={c['kx']}  cosφ={c['cosphi']}  "
                 f"线缆 {wire_spec}")
        els.append({"type": "text", "x": tx, "y": ry - 4, "s": line1, "size": 12,
                    "anchor": "start", "bold": True, "color": C_TEXT})
        els.append({"type": "text", "x": tx, "y": ry + 13, "s": line2, "size": 10,
                    "anchor": "start", "color": C_MUT})

    width = max(brk_x + brk_w + 360, 760)
    height = bus_bottom + 60
    els.insert(0, {"type": "rect", "x": 10, "y": 10, "w": width - 20, "h": height - 20,
                   "stroke": "#adb5bd", "fill": "none", "w": 1.5})
    els.append({"type": "text", "x": margin, "y": height - 22,
                "s": "注：本图为程序辅助生成，正式施工图须由注册电气工程师按 GB 50054 / GB 51348 校核。",
                "size": 10, "anchor": "start", "color": C_MUT})
    els.append({"type": "text", "x": width - 20, "y": height - 22,
                "s": f"回路 {n} 路", "size": 10, "anchor": "end", "color": C_MUT})

    return {"els": els, "width": width, "height": height}


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_svg(result):
    L = build_layout(result)
    w, h = L["width"], L["height"]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           f'font-family="\'Microsoft YaHei\',\'PingFang SC\',sans-serif" width="{w}" height="{h}">']
    out.append('<rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/>' % (w, h))
    for e in L["els"]:
        t = e["type"]
        if t == "line":
            out.append(f'<line x1="{e["x1"]}" y1="{e["y1"]}" x2="{e["x2"]}" y2="{e["y2"]}" '
                       f'stroke="{e["color"]}" stroke-width="{e["w"]}"/>')
        elif t == "rect":
            out.append(f'<rect x="{e["x"]}" y="{e["y"]}" width="{e["w"]}" height="{e["h"]}" '
                       f'stroke="{e["stroke"]}" fill="{e["fill"]}" stroke-width="{e["w"]}"/>')
        elif t == "text":
            weight = "700" if e.get("bold") else "400"
            out.append(f'<text x="{e["x"]}" y="{e["y"]}" font-size="{e["size"]}" '
                       f'fill="{e["color"]}" text-anchor="{e["anchor"]}" font-weight="{weight}">'
                       f'{_esc(e["s"])}</text>')
    out.append('</svg>')
    return "".join(out)


def export_dxf(result, path):
    try:
        import ezdxf
    except Exception as e:
        return False, f"缺少 ezdxf: {e}"
    L = build_layout(result)
    doc = ezdxf.new("R2010")
    doc.layers.add("BUS", color=1)
    doc.layers.add("BRK", color=5)
    doc.layers.add("WIRE", color=2)
    doc.layers.add("TEXT", color=7)
    doc.layers.add("BORDER", color=8)
    msp = doc.modelspace()
    for e in L["els"]:
        t = e["type"]
        if t == "line":
            layer = "BUS" if e["color"] == C_BUS else ("BRK" if e["color"] == C_LINE else "WIRE")
            msp.add_line((e["x1"], -e["y1"]), (e["x2"], -e["y2"]),
                         dxfattribs={"layer": layer, "lineweight": 30 if e["w"] >= 2 else 13})
        elif t == "rect":
            layer = "BORDER" if e.get("stroke") == "#adb5bd" else "BRK"
            x, y, w, h = e["x"], e["y"], e["w"], e["h"]
            pts = [(x, -y), (x + w, -y), (x + w, -(y + h)), (x, -(y + h)), (x, -y)]
            msp.add_lwpolyline(pts, dxfattribs={"layer": layer, "closed": True})
        elif t == "text":
            msp.add_text(_esc(e["s"]), dxfattribs={
                "layer": "TEXT", "height": e["size"], "color": 7,
                "insert": (e["x"], -e["y"]),
            })
    doc.saveas(path)
    return True, path


def dxf_to_dwg_via_autocad(dxf_path, dwg_path=None, version=8):
    """
    通过本机已安装的 AutoCAD 将 DXF 另存为 DWG。
    version: AcSaveAsType 枚举, 8=ac2013(AutoCAD 2014 原生, 兼容 2010+), 7=ac2010。
    注意: AutoCAD 2014 的 COM 不接受 version=7，故默认 8。返回 (ok, msg)。
    """
    import time
    import tempfile
    try:
        import win32com.client
        import win32com.client.gencache
        import pythoncom
    except Exception as e:
        return False, f"缺少 pywin32: {e}"
    # 每个线程使用 COM 前必须初始化(ThreadingHTTPServer 每个请求是新线程)
    try:
        pythoncom.CoInitialize()
    except pythoncom.com_error:
        pass
    if not os.path.exists(dxf_path):
        return False, f"DXF 不存在: {dxf_path}"
    if dwg_path is None:
        dwg_path = os.path.splitext(dxf_path)[0] + ".dwg"
    if os.path.exists(dwg_path):
        try:
            os.remove(dwg_path)
        except Exception:
            pass
    dxf_abs = os.path.abspath(dxf_path)
    dwg_abs = os.path.abspath(dwg_path)
    tdir = tempfile.gettempdir().lower()
    try:
        # gencache.EnsureDispatch 生成早期绑定类型库，方法表才完整(含 Close)
        acad = win32com.client.gencache.EnsureDispatch("AutoCAD.Application")
        acad.Visible = False
        time.sleep(1.2)  # 等 AutoCAD 完全就绪，避免 RPC_E_CALL_REJECTED
        # 清理本程序之前遗留的临时文档(路径在系统临时目录)，避免累积导致后续转换失败
        try:
            for d in list(acad.Documents):
                try:
                    if tdir in (d.Path or "").lower():
                        for _ in range(10):
                            try:
                                d.Close(False)  # 不保存直接关，避免弹"保存"对话框阻塞
                                break
                            except pythoncom.com_error as e:
                                if getattr(e, "args", [""])[0] == -2147418111:
                                    time.sleep(0.4)
                                    continue
                                break
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(0.3)
        doc = acad.Documents.Open(dxf_abs)
        time.sleep(0.5)
        doc.SaveAs(dwg_abs, version)
        # 关闭文档：AutoCAD 偶发"被呼叫方拒绝"，带重试；Close(False) 不弹保存对话框
        for _ in range(20):
            try:
                doc.Close(False)
                break
            except pythoncom.com_error as e:
                if getattr(e, "args", [""])[0] == -2147418111:
                    time.sleep(0.5)
                    continue
                break
    except pythoncom.com_error as e:
        return False, f"AutoCAD COM 错误(可能未启动/未授权/弹窗阻塞): {e}"
    except Exception as e:
        return False, f"转换失败: {e}"
    if os.path.exists(dwg_abs) and os.path.getsize(dwg_abs) > 0:
        return True, dwg_abs
    return False, "转换后未生成 DWG 文件(可能被 AutoCAD 弹窗中断)"


if __name__ == "__main__":
    from engine import demo_project, compute_project
    res = compute_project(demo_project())
    svg = render_svg(res)
    import os
    os.makedirs("output", exist_ok=True)
    open("output/_test.svg", "w", encoding="utf-8").write(svg)
    ok, msg = export_dxf(res, "output/_test.dxf")
    print("SVG 字节:", len(svg), "| DXF:", ok, msg)
