# -*- coding: utf-8 -*-
"""构建期生成程序图标 app_icon.ico（仅打包用，运行时不需要）。"""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
ico = os.path.join(HERE, "app_icon.ico")

try:
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([3, 3, size - 3, size - 3], radius=14, fill=(37, 99, 235, 255))
    cx = size // 2
    bolt = [(cx - 6, 14), (cx + 13, 14), (cx - 1, 33), (cx + 10, 33), (cx - 15, 54),
            (cx - 2, 35), (cx - 15, 35)]
    d.polygon(bolt, fill=(255, 214, 10, 255))
    img.save(ico, sizes=[(64, 64), (48, 48), (32, 32), (16, 16)])
    print("图标已生成:", ico, os.path.getsize(ico), "字节")
except Exception as e:
    print("图标生成失败(将使用默认图标):", e)
