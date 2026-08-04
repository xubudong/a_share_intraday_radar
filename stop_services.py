from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
VENV_DIR = BASE_DIR / ".venv"
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


def run_stop(host: str, port: int) -> int:
    python = venv_python()
    if not python.exists():
        print(f"未找到虚拟环境 Python：{python}")
        print("请先准备 .venv 并安装依赖，或直接使用当前 Python 执行 radar.py stop。")
        return 1

    command = [
        str(python),
        str(BASE_DIR / "radar.py"),
        "stop",
        "--host",
        host,
        "--port",
        str(port),
    ]
    print("停止 A股个股盘中买点雷达")
    print(f"项目目录：{BASE_DIR}")
    print(f"> {' '.join(command)}")
    return subprocess.run(command, cwd=BASE_DIR, check=False).returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="停止 A 股盘中买点雷达服务。")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_stop(args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
