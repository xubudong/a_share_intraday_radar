from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch A Share Intraday Radar.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8030)
    parser.add_argument("--pid-file", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    record = {
        "pid": os.getpid(),
        "host": args.host,
        "port": args.port,
        "start_time_utc": datetime.now(timezone.utc).isoformat(),
    }
    args.pid_file.write_text(json.dumps(record, indent=2), encoding="ascii")

    try:
        uvicorn.run("app.server:app", host=args.host, port=args.port)
    finally:
        try:
            current = json.loads(args.pid_file.read_text(encoding="ascii"))
            if current.get("pid") == os.getpid():
                args.pid_file.unlink()
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass


if __name__ == "__main__":
    main()
