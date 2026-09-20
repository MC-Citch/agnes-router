#!/usr/bin/env python3
"""
不绘来世 - Agnes & DeepSeek 智能路由桌面版

使用 pywebview 将 Web UI 嵌入原生桌面窗口，无需浏览器。
启动方式:
    python desktop.py
    或使用 PyInstaller 打包成 .exe 后双击运行
"""

import os
import sys
import threading
import time
from pathlib import Path

# ---- 确保工作目录正确 ----
# PyInstaller 打包后：exe 所在目录为数据目录
# 开发模式：脚本所在目录
if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).parent)
else:
    os.chdir(Path(__file__).parent)


def _start_server(host: str = "127.0.0.1", port: int = 8800):
    """在后台线程启动 FastAPI 服务器。"""
    import uvicorn
    from router import create_app, cfg as _cfg

    app = create_app()

    # 启动校验
    warnings = _cfg.validate()
    if warnings:
        print("[配置警告]")
        for w in warnings:
            print(f"  ! {w}")
        print()

    uvicorn.run(app, host=host, port=port, log_level="warning")


def _wait_for_server(url: str, timeout: float = 30.0) -> bool:
    """轮询等待服务器就绪，返回是否成功。"""
    import urllib.request
    import urllib.error

    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=1.5)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def main():
    import webview
    from router import cfg

    host = cfg.host
    port = cfg.port
    url = f"http://{host}:{port}"

    print("=" * 50)
    print("  不绘来世 v3.1 桌面版")
    print("=" * 50)
    print(f"  地址: {url}")
    print()

    # 1. 后台启动 FastAPI 服务
    print("[1/3] 启动后端服务...")
    server_thread = threading.Thread(
        target=_start_server, args=(host, port), daemon=True,
    )
    server_thread.start()

    # 2. 等待服务就绪
    print("[2/3] 等待服务就绪...")
    if not _wait_for_server(f"{url}/health", timeout=15):
        print("  [警告] 服务启动超时，仍在尝试打开窗口...")
    else:
        print("  [OK] 服务已就绪")

    # 3. 创建桌面窗口
    print("[3/3] 创建桌面窗口...")
    webview.create_window(
        title="不绘来世",
        url=url,
        width=1100,
        height=750,
        min_size=(800, 500),
        confirm_close=False,
        text_select=True,
    )

    # 启动 webview 事件循环（阻塞直到用户关闭窗口）
    webview.start()

    print("\n窗口已关闭，感谢使用！")


if __name__ == "__main__":
    main()
