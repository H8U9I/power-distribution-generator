# -*- coding: utf-8 -*-
import os, zipfile

REL = r"H:\配电图生成器\release"
OUT = r"H:\配电图生成器\配电图自动生成器_解压即用.zip"
include = ["配电图生成器.exe", "vc_redist.x64.exe", "软件使用说明.docx", "依赖说明.txt"]

if os.path.exists(OUT):
    os.remove(OUT)

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for f in include:
        p = os.path.join(REL, f)
        if not os.path.exists(p):
            raise SystemExit(f"缺少文件: {p}")
        z.write(p, arcname=f)  # 平铺，不带目录前缀
        print("已加入:", f, os.path.getsize(p), "字节")

print("\n=== 压缩包完成 ===")
print("路径:", OUT)
print("大小:", os.path.getsize(OUT), "字节")
# 列出内容校验
with zipfile.ZipFile(OUT) as z:
    print("包含:", z.namelist())
