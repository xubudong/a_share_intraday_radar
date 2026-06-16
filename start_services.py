from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
VENV_DIR = BASE_DIR / ".venv"
REQUIREMENTS = BASE_DIR / "requirements.txt"
DEFAULT_HOST = os.getenv("WEB_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("WEB_PORT", "8030"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


def is_windows() -> bool:
    return os.name == "nt"


def venv_python() -> Path:
    scripts_dir = "Scripts" if is_windows() else "bin"
    exe_name = "python.exe" if is_windows() else "python"
    return VENV_DIR / scripts_dir / exe_name


def validate_project_layout() -> list[str]:
    checks = [
        (BASE_DIR / "radar.py", "缺少进程控制入口 radar.py"),
        (BASE_DIR / "app" / "server.py", "缺少后端入口 app/server.py"),
        (BASE_DIR / "static" / "index.html", "缺少前端页面 static/index.html"),
        (REQUIREMENTS, "缺少依赖文件 requirements.txt"),
    ]
    return [message for path, message in checks if not path.exists()]


def run(command: list[str], *, cwd: Path = BASE_DIR) -> int:
    print(f"> {' '.join(command)}")
    return subprocess.run(command, cwd=cwd, check=False).returncode


def ensure_venv() -> int:
    python = venv_python()
    if python.exists():
        print(f"虚拟环境：{python}")
        return 0

    print(f"创建虚拟环境：{VENV_DIR}")
    return run([sys.executable, "-m", "venv", str(VENV_DIR)])


def install_dependencies() -> int:
    print("安装/检查依赖：requirements.txt")
    return run([str(venv_python()), "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def run_radar(command: str, host: str, port: int) -> int:
    print(f"执行服务命令：{command}")
    code = run(
        [
            str(venv_python()),
            str(BASE_DIR / "radar.py"),
            command,
            "--host",
            host,
            "--port",
            str(port),
        ]
    )
    if code == 0:
        print()
        print("服务信息：")
        print(f"- 页面：http://{host}:{port}")
        print(f"- 状态：{venv_python()} radar.py status")
        print(f"- 停止：py stop_services.py")
        print(f"- 日志：{BASE_DIR / '.radar.out.log'}")
    return code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 A 股盘中买点雷达服务。")
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址，默认读取 WEB_HOST 或 127.0.0.1。")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口，默认读取 WEB_PORT 或 8030。")
    parser.add_argument("--restart", action="store_true", help="先停止当前项目实例，再重新启动。")
    parser.add_argument("--setup-only", action="store_true", help="只创建虚拟环境并安装依赖，不启动服务。")
    parser.add_argument("--no-install", action="store_true", help="跳过依赖安装，直接启动。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print("A股个股盘中买点雷达")
    print(f"项目目录：{BASE_DIR}")
    print(f"目标地址：http://{args.host}:{args.port}")
    print()

    layout_errors = validate_project_layout()
    if layout_errors:
        print("项目结构检查失败：")
        for error in layout_errors:
            print(f"- {error}")
        return 1

    code = ensure_venv()
    if code != 0:
        return code

    if not args.no_install:
        code = install_dependencies()
        if code != 0:
            return code

    if args.setup_only:
        print("环境准备完成。")
        return 0

    return run_radar("restart" if args.restart else "start", args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
