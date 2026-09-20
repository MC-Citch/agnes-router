#!/usr/bin/env python3
"""
不绘来世 - 一键启动

  双击运行或在终端执行: python launcher.py

会自动:
  1. 校验 API Key 配置
  2. 启动后端 API 服务 (端口 8800)
  3. 打开浏览器访问前端界面
"""

import os
import sys
import asyncio
from pathlib import Path

# 切换到项目目录
os.chdir(Path(__file__).parent)

import router


async def main():
    print("=" * 50)
    print("  不绘来世 v3.1")
    print("=" * 50)

    # 启动前校验
    from config import cfg
    warnings = cfg.validate()
    if warnings:
        print("\n  [配置警告]")
        for w in warnings:
            print(f"    ! {w}")
        print()

    await router._cmd_serve([])


if __name__ == "__main__":
    asyncio.run(main())
