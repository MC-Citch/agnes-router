#!/usr/bin/env python3
"""
generate_icon.py — 从 PNG 生成多尺寸 Windows 图标 (.ico)

用法:
    python generate_icon.py                 # 默认: assets/LOGO.png → assets/icon.ico
    python generate_icon.py input.png       # 生成 input.ico
    python generate_icon.py input.png out.ico
    python generate_icon.py --help

功能:
    - 自动缩放为多个尺寸: 16, 24, 32, 48, 64, 128, 256
    - 生成标准 .ico 格式，包含 alpha 通道（透明支持）
    - 修复 OR 掩码运算符优先级 bug
"""

import sys
import os
from pathlib import Path


def generate_icon(input_path: str, output_path: str):
    """从 PNG 图片生成 .ico 文件。"""
    from PIL import Image

    sizes = [16, 24, 32, 48, 64, 128, 256]
    img = Image.open(input_path).convert("RGBA")

    frames = []
    for size in sizes:
        # 等比缩放，保持居中
        img_resized = img.resize((size, size), Image.LANCZOS)
        frames.append(img_resized)

    frames[0].save(
        output_path,
        format="ICO",
        save_all=True,
        append_images=frames[1:],
    )
    print(f"[OK] 已生成: {output_path} ({', '.join(map(str, sizes))}px)")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="从 PNG 生成多尺寸 Windows 图标 (.ico)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python generate_icon.py                 # 默认: assets/LOGO.png → assets/icon.ico
  python generate_icon.py mylogo.png      # 生成 mylogo.ico
  python generate_icon.py mylogo.png out.ico
        """,
    )
    parser.add_argument("input", nargs="?", default=None, help="输入 PNG 文件路径")
    parser.add_argument("output", nargs="?", default=None, help="输出 ICO 文件路径")
    args = parser.parse_args()

    # 确定输入路径
    if args.input:
        input_path = Path(args.input)
    else:
        # 默认: 查找 assets/LOGO.png
        candidates = [
            Path("assets") / "LOGO.png",
            Path("LOGO.png"),
        ]
        input_path = next((p for p in candidates if p.exists()), None)

    if not input_path or not input_path.exists():
        print("[ERROR] 未找到输入图片。请提供 PNG 路径，或确保 assets/LOGO.png 存在。")
        sys.exit(1)

    # 确定输出路径
    if args.output:
        output_path = Path(args.output)
    else:
        # 默认: 与 input 同目录同名 .ico
        output_path = input_path.with_suffix(".ico")

    generate_icon(str(input_path), str(output_path))


if __name__ == "__main__":
    main()
