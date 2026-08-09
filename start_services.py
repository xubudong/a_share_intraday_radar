from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
MANAGER = BASE_DIR / "scripts" / "manage.py"
DEFAULT_HOST = os.getenv("WEB_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("WEB_PORT", "8030"))


def venv_python() -> Path:
    return BASE_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def validate_project_layout() -> list[str]:
    checks = [
        (MANAGER, "缺少统一进程管理入口 scripts/manage.py"),
        (BASE_DIR / "radar.py", "缺少进程控制器 radar.py"),
        (BASE_DIR / "app" / "server.py", "缺少后端入口 app/server.py"),
        (BASE_DIR / "static" / "index.html", "缺少前端页面 static/index.html"),
        (BASE_DIR / "requirements.txt", "缺少依赖文件 requirements.txt"),
    ]
    return [message for path, message in checks if not path.exists()]


def run_manager(command: str, host: str, port: int) -> int:
    python = venv_python()
    if not python.exists():
        print(f"未找到项目虚拟环境 Python：{python}")
        print("请先创建 .venv 并安装 requirements.txt 中的依赖。")
        return 1

    args = [str(python), str(MANAGER), command, "--host", host, "--port", str(port)]
    return subprocess.run(args, cwd=BASE_DIR, check=False).returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 A 股盘中买点雷达服务。")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--restart", action="store_true", help="停止现有实例后重新启动。")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    errors = validate_project_layout()
    if errors:
        print("项目结构检查失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    return run_manager("restart" if args.restart else "start", args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
