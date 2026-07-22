# -*- coding: utf-8 -*-
"""
配电图生成器 - Web 服务 (零前端依赖，stdlib http.server)
启动: python app.py  ->  浏览器打开 http://127.0.0.1:18800
打包为单文件 exe 后: 双击即自动起服务并打开浏览器
"""
import sys
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import engine
from engine import (compute_project, demo_project, FIRE_RATINGS, CABLE_TYPES,
                     CATEGORY_DEFAULTS, WIRE_TABLE, BREAKER_SERIES)
import exporters

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 18800

CATEGORY_LABEL = {"socket": "插座回路", "lighting": "照明回路", "device": "设备回路"}
CATEGORY_LABEL_EN = {"socket": "socket", "lighting": "lighting", "device": "device"}


def _resolve_output_dir():
    """输出目录：优先 exe 同目录(软件旁)，失败则用用户文档/AppData，保证可写。"""
    cands = []
    if getattr(sys, "frozen", False):
        cands.append(os.path.dirname(sys.executable))
    cands.append(os.path.join(os.path.expanduser("~"), "Documents", "配电图生成器"))
    cands.append(os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "配电图生成器"))
    for base in cands:
        d = os.path.join(base, "output")
        try:
            os.makedirs(d, exist_ok=True)
            t = os.path.join(d, ".writable_test")
            with open(t, "w") as f:
                f.write("1")
            os.remove(t)
            return d
        except Exception:
            continue
    d = os.path.join(HERE, "output")
    os.makedirs(d, exist_ok=True)
    return d


OUT = _resolve_output_dir()


def _standards():
    return {
        "fire_ratings": {k: {"prefix": v["prefix"], "derate": v["derate"], "desc": v["desc"]}
                         for k, v in FIRE_RATINGS.items()},
        "cable_types": CABLE_TYPES,
        "wire_table": WIRE_TABLE,
        "breaker_series": BREAKER_SERIES,
        "categories": CATEGORY_DEFAULTS,
        "category_labels": CATEGORY_LABEL,
    }


def _json_body(req):
    length = int(req.headers.get("Content-Length", 0) or 0)
    if not length:
        return {}
    raw = req.rfile.read(length)
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _send_json(req, obj, code=200):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    req.send_response(code)
    req.send_header("Content-Type", "application/json; charset=utf-8")
    req.send_header("Content-Length", str(len(data)))
    req.send_header("Access-Control-Allow-Origin", "*")
    req.end_headers()
    req.wfile.write(data)


def _send_file(req, path, mime, download_name=None):
    from urllib.parse import quote
    with open(path, "rb") as f:
        data = f.read()
    req.send_response(200)
    req.send_header("Content-Type", mime)
    req.send_header("Content-Length", str(len(data)))
    if download_name:
        # RFC 5987: ASCII fallback + UTF-8 编码中文名(避免 latin-1 报错，浏览器显示中文下载名)
        ext = download_name.rsplit(".", 1)[-1] if "." in download_name else "bin"
        ascii_name = f"peidian.{ext}"
        enc = quote(download_name)
        req.send_header("Content-Disposition",
                        f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{enc}')
    req.send_header("Access-Control-Allow-Origin", "*")
    req.end_headers()
    req.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # 安静

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self._serve(os.path.join(HERE, "static", "index.html"), "text/html; charset=utf-8")
        elif p == "/api/standards":
            _send_json(self, _standards())
        elif p == "/api/demo":
            _send_json(self, demo_project())
        elif p == "/api/output/svg":
            self._serve(os.path.join(OUT, "配电系统图.svg"), "image/svg+xml; charset=utf-8")
        elif p == "/api/output/dxf":
            self._serve(os.path.join(OUT, "配电系统图.dxf"), "application/dxf", "配电系统图.dxf")
        else:
            _send_json(self, {"error": "not found"}, 404)

    def do_POST(self):
        p = urlparse(self.path).path
        body = _json_body(self)
        if p == "/api/compute":
            res = compute_project(body)
            _send_json(self, res)
        elif p == "/api/export/svg":
            res = compute_project(body)
            svg = exporters.render_svg(res)
            path = os.path.join(OUT, "配电系统图.svg")
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
            _send_json(self, {"ok": True, "path": path, "svg": svg})
        elif p == "/api/export/dxf":
            import tempfile
            res = compute_project(body)
            # 临时文件生成，避免与已打开的 DXF 锁冲突
            tmpdir = tempfile.gettempdir()
            dxf_tmp = os.path.join(tmpdir, "pd_dxf_%d.dxf" % os.getpid())
            ok, msg = exporters.export_dxf(res, dxf_tmp)
            if ok:
                self._serve(dxf_tmp, "application/octet-stream", "配电系统图.dxf")
                try:
                    os.remove(dxf_tmp)
                except Exception:
                    pass
            else:
                _send_json(self, {"ok": False, "msg": msg}, 500)
        elif p == "/api/export/report":
            res = compute_project(body)
            path = os.path.join(OUT, "负荷计算书.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(_report_md(res))
            _send_json(self, {"ok": True, "path": path})
        elif p == "/api/export/dwg":
            import tempfile
            res = compute_project(body)
            # 用唯一临时 DXF，避免与已打开的 DXF 锁冲突
            tmpdir = tempfile.gettempdir()
            dxf_tmp = os.path.join(tmpdir, "pd_dwg_%d.dxf" % os.getpid())
            exporters.export_dxf(res, dxf_tmp)
            dwg_path = os.path.join(OUT, "配电系统图.dwg")
            ok, msg = exporters.dxf_to_dwg_via_autocad(dxf_tmp, dwg_path)
            try:
                os.remove(dxf_tmp)
            except Exception:
                pass
            if ok:
                self._serve(dwg_path, "application/octet-stream", "配电系统图.dwg")
            else:
                _send_json(self, {"ok": False, "msg": msg}, 500)
        else:
            _send_json(self, {"error": "not found"}, 404)

    def _serve(self, path, mime, download_name=None):
        if not os.path.exists(path):
            _send_json(self, {"error": f"文件不存在: {path}"}, 404)
            return
        _send_file(self, path, mime, download_name)


def _report_md(res):
    lines = [f"# {res['meta'].get('name','配电箱')} 负荷计算书\n"]
    lines.append(f"- 系统: {'三相380V' if res['v_system']=='three' else '单相220V'}")
    lines.append(f"- 防火等级: {res['fire_rating']}  线缆类型: {res['cable_type']}")
    t = res["totals"]
    lines.append(f"- 设备总功率: {t['P_raw_kW']}kW  计算负荷: {t['P_demand_kW']}kW")
    lines.append(f"- 回路数: {t['loop_count']}（单相 {t['single_loops']} / 三相 {t['three_phase_loops']}）")
    m = res["main"]
    lines.append(f"- 总开关: C{m['In_main']}  进线: {m['incoming']}  三相不平衡: {m['imbalance_pct']}%\n")
    lines.append("## 回路明细\n")
    lines.append("| 回路 | 类型 | 相 | 设备 | 功率(W) | kx | cosφ | Ijs(A) | 空开 | 线缆(mm²) | RCD |")
    lines.append("|------|------|----|------|---------|----|------|--------|------|-----------|-----|")
    for c in res["circuits"]:
        lines.append(f"| {c['name']} | {c['group']} | {c.get('phase','')} | {c['devices_text']} | "
                     f"{c['total_p']} | {c['kx']} | {c['cosphi']} | {c['Ijs']} | C{c['In']} | "
                     f"{c['wire_area']} | {'是' if c['rcd'] else '否'} |")
    return "\n".join(lines) + "\n"


def run():
    srv = None
    port = PORT
    # 端口被占用(如开发版还在跑)则往后找空闲端口
    while port < PORT + 50:
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            port += 1
    if srv is None:
        return
    url = f"http://127.0.0.1:{port}"

    def open_browser():
        import time
        import webbrowser
        if os.environ.get("NO_AUTOBROWSE"):
            return
        time.sleep(1.5)  # 等服务绑定完成
        try:
            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=open_browser, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    run()
