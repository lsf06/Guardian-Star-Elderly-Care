#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成项目主页的二维码（深灰墨色 + 暖白底，圆角模块）。

用法（仓库根目录）：
    python tools/make_qr.py
    python tools/make_qr.py --url https://example.com --out qr-code.png

为什么用 ERROR_CORRECT_H：页面上的二维码只有约 90–110 px 显示尺寸，
投影仪、打印、手机镜头脏都会掉对比度。H 级容错 30%，比 M 级多花几个模块，
但换来的是"扫不出来的概率"下降——这个页面上二维码的唯一用途就是被人扫。

依赖：pip install "qrcode[pil]"
"""

import argparse
import sys

URL = "https://lsf06.github.io/Guardian-Star-Elderly-Care/"

# 与 index.html 的配色变量保持一致
INK = (43, 41, 38)        # --ink   #2B2926
PAPER = (248, 245, 240)   # --bg    #F8F5F0


def build(url: str, out: str, box_size: int, border: int, radius: float) -> str:
    import qrcode
    from qrcode.image.styledpil import StyledPilImage
    from qrcode.image.styles.moduledrawers.pil import RoundedModuleDrawer
    from qrcode.image.styles.colormasks import SolidFillColorMask

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=RoundedModuleDrawer(radius_ratio=radius),
        color_mask=SolidFillColorMask(back_color=PAPER, front_color=INK),
    )
    img.save(out)
    return f"{img.size[0]}x{img.size[1]}"


def verify(path: str, expect: str) -> bool:
    """用独立解码器回读，确认这张图真的能扫。装不上就跳过，不阻断生成。"""
    try:
        import zxingcpp
        from PIL import Image
    except ImportError:
        print("  [跳过] 未安装 zxing-cpp，无法回读校验")
        return True

    results = zxingcpp.read_barcodes(Image.open(path))
    if not results:
        print("  [失败] 解码器没读到任何二维码")
        return False
    got = results[0].text
    ok = got == expect
    print(f"  解码结果: {got}")
    print(f"  与预期一致: {'是' if ok else '否'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=URL)
    ap.add_argument("--out", default="qr-code.png")
    ap.add_argument("--box-size", type=int, default=24, help="每个模块的像素数")
    ap.add_argument("--border", type=int, default=4, help="静区宽度（模块数），规范要求 >= 4")
    ap.add_argument("--radius", type=float, default=0.55, help="圆角比例 0–1，越大越圆")
    args = ap.parse_args()

    print(f"内容: {args.url}")
    size = build(args.url, args.out, args.box_size, args.border, args.radius)
    print(f"已写入: {args.out}  ({size} px)")
    if not verify(args.out, args.url):
        print("校验未通过，请调大 --box-size 或把 --radius 降到 0.3 以下重试")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
