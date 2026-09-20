#!/usr/bin/env python3
"""
通用 Python 打包脚本

用法:
    python build.py              # 自动打包
    python build.py --clean      # 清理后重新打包
    python build.py --verbose    # 显示详细日志
    python build.py --name "MyApp"  # 自定义应用名

功能:
    1. 自动检测入口文件 (launcher.py / desktop.py / main.py / app.py)
    2. 自动创建干净虚拟环境 (venv/)
    3. 自动安装 requirements.txt 中的依赖
    4. 自动扫描 static/ assets/ 等资源目录
    5. 自动检测图标文件 (icon.ico)
    6. 使用 PyInstaller 打包成单文件 exe

输出:
    dist/应用名.exe
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


# ============================================================
# 配置区 (可根据项目修改)
# ============================================================

# 入口文件 (优先匹配顺序)
ENTRY_POINTS = ["desktop.py", "launcher.py", "main.py", "app.py"]

# 排除的目录/文件 (不打包进 exe)
EXCLUDE_DIRS = ["venv", "venv_new", "__pycache__", ".git", "dist", "build"]
EXCLUDE_FILES = ["*.pyc", "*.pyo", "*.pyd", ".DS_Store", "*.bak"]

# PyInstaller 参数
PYINSTALLER_ARGS_DEFAULT = [
    "--onefile",          # 单文件 exe
    "--windowed",         # 无控制台窗口 (GUI 应用)
    "--clean",            # 清理临时文件
    "--noconfirm",        # 覆盖输出目录
]

# 平台相关的路径分隔符
SEP = ";" if sys.platform == "win32" else ":"


# ============================================================
# 工具函数
# ============================================================

def log(msg: str, level: str = "info"):
    """打印带颜色的日志"""
    colors = {
        "info":    "\033[36m",   # 青色
        "success": "\033[32m",   # 绿色
        "warn":    "\033[33m",   # 黄色
        "error":   "\033[31m",   # 红色
        "reset":   "\033[0m",
    }
    prefix = {
        "info":    "[INFO]",
        "success": "[OK]  ",
        "warn":    "[WARN]",
        "error":   "[FAIL]",
    }
    color = colors.get(level, colors["reset"])
    print(f"{color}{prefix.get(level, '')} {msg}{colors['reset']}")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """运行命令，捕获输出"""
    log(f"运行: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            # 过滤特殊字符，只打印可打印行
            clean_line = ''.join(c for c in line if c.isprintable() or c in '\t\n\r')
            print(f"  {clean_line}")
    if result.returncode != 0 and check:
        log(f"命令失败 (exit {result.returncode})", "error")
        if result.stderr:
            clean_err = ''.join(c for c in result.stderr.strip().split('\n')[-5:] if any(ch.isprintable() for ch in c))
            log('\n'.join(clean_err), "error")
        sys.exit(1)
    return result


def get_python_path() -> Path:
    """获取当前 Python 解释器路径"""
    return Path(sys.executable).resolve()


def get_venv_python(venv_dir: Path) -> Path:
    """获取 venv 中的 Python 路径 (跨平台)"""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    else:
        return venv_dir / "bin" / "python"


def get_pip_path(venv_dir: Path) -> Path:
    """获取 venv 中的 pip 路径"""
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "pip.exe"
    else:
        return venv_dir / "bin" / "pip"


# ============================================================
# 主流程
# ============================================================

def detect_entry_point(project_dir: Path) -> Path | None:
    """检测入口文件"""
    for entry in ENTRY_POINTS:
        path = project_dir / entry
        if path.exists():
            return path
    return None


def detect_resources(project_dir: Path) -> list[dict]:
    """检测资源目录和图标"""
    resources = []

    # 静态资源目录 (common names)
    static_names = ["static", "assets", "data", "public", "media", "templates", "locales"]
    for name in static_names:
        dir_path = project_dir / name
        if dir_path.is_dir():
            resources.append({
                "type": "dir",
                "src": str(dir_path),
                "dst": name,
                "exists": True,
            })

    # 图标文件
    icon_patterns = ["icon.ico", "icon.png", "icon.svg", "app.ico", "app.png"]
    for pattern in icon_patterns:
        icon_path = project_dir / "assets" / pattern
        if not icon_path.exists():
            icon_path = project_dir / pattern
        if icon_path.exists():
            resources.append({
                "type": "icon",
                "path": str(icon_path),
            })
            break

    return resources


def create_venv(venv_dir: Path, requirements_file: Path) -> tuple[Path, Path]:
    """创建或复用虚拟环境"""
    venv_python = get_venv_python(venv_dir)

    if venv_python.exists():
        log(f"发现已有 venv: {venv_dir}")
        # 检查是否安装了 PyInstaller
        try:
            run([str(venv_python), "-c", "import PyInstaller"], check=False)
            log("PyInstaller 已安装", "success")
        except SystemExit:
            log("PyInstaller 未安装，正在安装...", "warn")
            run([str(venv_python), "-m", "pip", "install", "pyinstaller>=6.0"])
    else:
        log(f"创建虚拟环境: {venv_dir}")
        run([str(get_python_path()), "-m", "venv", str(venv_dir)])

        # 升级 pip
        log("升级 pip...")
        run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])

        # 安装 requirements.txt
        if requirements_file.exists():
            log(f"安装依赖 (从 {requirements_file.name})...")
            run([str(venv_python), "-m", "pip", "install", "-r", str(requirements_file)])
        else:
            log(f"警告: 未找到 {requirements_file.name}，跳过依赖安装", "warn")

        # 确保 PyInstaller 已安装
        log("安装 PyInstaller...")
        run([str(venv_python), "-m", "pip", "install", "pyinstaller>=6.0"])

    return venv_python, get_pip_path(venv_dir)


def build_pyinstaller(venv_python: Path, project_dir: Path, entry_point: Path,
                      resources: list[dict], app_name: str, verbose: bool = False) -> Path:
    """执行 PyInstaller 打包"""
    args = list(PYINSTALLER_ARGS_DEFAULT)

    # 入口文件
    args.append(str(entry_point))

    # 应用名称
    args.extend(["--name", app_name])

    # 添加资源文件
    icon_path = None

    for res in resources:
        if res["type"] == "dir":
            src = res["src"]
            dst = res["dst"]
            # 每个目录单独添加，避免路径分隔符问题
            args.extend(["--add-data", f"{src}{os.pathsep}{dst}"])
            log(f"  添加资源: {src} -> {dst}/", "info")
        elif res["type"] == "icon":
            icon_path = res["path"]
            log(f"  使用图标: {icon_path}", "info")

    if icon_path:
        args.extend(["--icon", icon_path])

    # 隐藏导入 (常用 Python 库)
    hidden_imports = [
        "uvicorn", "uvicorn.loops", "uvicorn.loops.auto",
        "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan", "uvicorn.lifespan.on",
        "fastapi", "starlette", "starlette.routing",
        "anyio", "anyio._backends", "anyio._backends._asyncio",
        "httpx", "httpcore", "httpcore._async",
        "openai",
        "dotenv",
    ]
    for imp in hidden_imports:
        args.extend(["--hidden-import", imp])

    # 收集子模块 (可选，防止遗漏)
    # args.extend(["--collect-submodules", "uvicorn"])

    if verbose:
        args.append("--debug=all")

    log("=" * 50)
    log(f"开始打包: {app_name}")
    log(f"入口: {entry_point.name}")
    log(f"Python: {venv_python}")
    log("=" * 50)

    run([str(venv_python), "-m", "PyInstaller"] + args, check=False)

    return project_dir / "dist" / f"{app_name}.exe"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="通用 Python 打包脚本")
    parser.add_argument("--clean", action="store_true", help="清理 dist/ 和 build/ 后重新打包")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示详细日志")
    parser.add_argument("--name", "-n", help="自定义应用名称 (默认从目录名获取)")
    args = parser.parse_args()

    # ============================================================
    # 1. 准备工作目录
    # ============================================================
    project_dir = Path(__file__).parent.resolve()
    os.chdir(project_dir)
    log(f"工作目录: {project_dir}", "info")

    # 清理 (如果指定)
    if args.clean:
        for d in ["dist", "build"]:
            if (project_dir / d).exists():
                log(f"清理 {d}/...", "info")
                shutil.rmtree(project_dir / d)
        for f in project_dir.glob("*.spec"):
            log(f"清理 {f.name}...", "info")
            f.unlink()

    # ============================================================
    # 2. 检测入口文件
    # ============================================================
    entry_point = detect_entry_point(project_dir)
    if not entry_point:
        log(f"未找到入口文件，尝试以下名称:\n  {'  '.join(ENTRY_POINTS)}", "error")
        sys.exit(1)
    log(f"入口文件: {entry_point.name}", "success")

    # ============================================================
    # 3. 获取应用名称
    # ============================================================
    app_name = args.name or project_dir.name
    log(f"应用名称: {app_name}", "info")

    # ============================================================
    # 4. 检测资源
    # ============================================================
    resources = detect_resources(project_dir)
    log(f"发现 {len([r for r in resources if r['type'] == 'dir'])} 个资源目录", "info")

    # ============================================================
    # 5. 创建/复用 venv
    # ============================================================
    venv_dir = project_dir / "venv"
    requirements_file = project_dir / "requirements.txt"
    venv_python, pip_path = create_venv(venv_dir, requirements_file)
    log(f"Python 环境就绪: {venv_python}", "success")

    # ============================================================
    # 6. 执行打包
    # ============================================================
    output_exe = build_pyinstaller(
        venv_python=venv_python,
        project_dir=project_dir,
        entry_point=entry_point,
        resources=resources,
        app_name=app_name,
        verbose=args.verbose,
    )

    # ============================================================
    # 7. 结果
    # ============================================================
    if output_exe.exists():
        size_mb = output_exe.stat().st_size / (1024 * 1024)
        log(f"打包成功! 输出: {output_exe}", "success")
        log(f"文件大小: {size_mb:.1f} MB", "info")
        print()
        print("=" * 50)
        print("  使用说明:")
        print(f"  1. 将 dist/{app_name}.exe 发给用户")
        print(f"  2. 在同目录下放一个 .env 文件 (API Key)")
        print(f"  3. 用户双击即可运行")
        print("=" * 50)
    else:
        log("打包失败，请检查上方错误信息", "error")
        sys.exit(1)


if __name__ == "__main__":
    main()
