from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REQUIREMENTS = BASE_DIR / "requirements.txt"
DEFAULT_HOST = os.getenv("WEB_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("WEB_PORT", "8030"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


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


def run_radar(command: str, host: str, port: int) -> int:
    print(f"执行服务命令：{command}")
    code = run(
        [
            sys.executable,
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
        print(f"- 状态：{sys.executable} radar.py status --host {host} --port {port}")
        print(f"- 停止：{sys.executable} stop_services.py --host {host} --port {port}")
        print(f"- 日志：{BASE_DIR / '.radar.out.log'}")
    return code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="启动 A 股盘中买点雷达服务。")
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址，默认读取 WEB_HOST 或 0.0.0.0。")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口，默认读取 WEB_PORT 或 8030。")
    parser.add_argument("--restart", action="store_true", help="先停止当前项目实例，再重新启动。")
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

    return run_radar("restart" if args.restart else "start", args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
