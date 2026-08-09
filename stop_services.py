from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MANAGER = BASE_DIR / "scripts" / "manage.py"
DEFAULT_HOST = os.getenv("WEB_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("WEB_PORT", "8030"))


def venv_python() -> Path:
    return BASE_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_stop(host: str, port: int) -> int:
    python = venv_python()
    if not python.exists():
        print(f"未找到项目虚拟环境 Python：{python}")
        print("请先创建 .venv 并安装 requirements.txt 中的依赖。")
        return 1

    command = [
        str(python),
        str(MANAGER),
        "stop",
        "--host",
        host,
        "--port",
        str(port),
    ]
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
