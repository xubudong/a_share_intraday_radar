from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.config import ROOT_DIR
from app.instance import APP_ID, root_fingerprint


PID_FILE = ROOT_DIR / ".radar.pid"
STDOUT_LOG = ROOT_DIR / ".radar.out.log"
STDERR_LOG = ROOT_DIR / ".radar.err.log"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8030


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A Share Intraday Radar process controller.")
    parser.add_argument("command", choices=("start", "stop", "restart", "status"))
    parser.add_argument("--host", default=os.getenv("WEB_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("WEB_PORT", DEFAULT_PORT)))
    return parser.parse_args(argv)


def probe_host(host: str) -> str:
    return DEFAULT_HOST if host in {"0.0.0.0", "::"} else host


def instance_url(host: str, port: int) -> str:
    return f"http://{probe_host(host)}:{port}/api/instance"


def fetch_instance(host: str, port: int, timeout: float = 1.5) -> dict[str, Any] | None:
    return fetch_json(instance_url(host, port), timeout=timeout)


def fetch_json(url: str, timeout: float = 1.5) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def is_this_project(instance: dict[str, Any] | None) -> bool:
    return bool(
        instance
        and instance.get("app_id") == APP_ID
        and instance.get("root_fingerprint") == root_fingerprint(ROOT_DIR)
    )


def is_legacy_project(host: str, port: int) -> bool:
    health = fetch_json(f"http://{probe_host(host)}:{port}/api/health")
    cache_path = health.get("cache_path") if health else None
    if not cache_path:
        return False
    try:
        return Path(cache_path).resolve() == (ROOT_DIR / "data" / "state_cache.json").resolve()
    except OSError:
        return False


def listener_pids(port: int) -> set[int]:
    if os.name != "nt":
        return set()
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[3].upper() != "LISTENING":
            continue
        local_address = parts[1]
        if local_address.rsplit(":", 1)[-1] != str(port):
            continue
        try:
            pids.add(int(parts[4]))
        except ValueError:
            pass
    return pids


def port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((probe_host(host), port), timeout=0.8):
            return True
    except OSError:
        return False


def load_pid_record() -> dict[str, Any] | None:
    try:
        return json.loads(PID_FILE.read_text(encoding="ascii"))
    except (FileNotFoundError, OSError, ValueError):
        return None


def valid_pid_record(record: dict[str, Any] | None) -> bool:
    return bool(
        record
        and record.get("app_id") == APP_ID
        and record.get("root_fingerprint") == root_fingerprint(ROOT_DIR)
        and record.get("pid")
        and record.get("host")
        and record.get("port")
    )


def remove_pid_file() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def wait_for_instance(host: str, port: int, timeout: float = 20) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        instance = fetch_instance(host, port)
        if is_this_project(instance):
            return instance
        time.sleep(0.25)
    return None


def find_available_port(host: str, start_port: int, attempts: int = 10) -> int | None:
    for candidate in range(start_port, start_port + attempts):
        if not port_is_open(host, candidate):
            return candidate
    return None


def process_detach_options() -> dict[str, Any]:
    if os.name == "nt":
        return {
            "creationflags": (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
            )
        }
    return {"start_new_session": True}


def wait_for_port_close(host: str, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_is_open(host, port):
            return True
        time.sleep(0.25)
    return not port_is_open(host, port)


def force_terminate_process_tree(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            check=False,
        )
        return result.returncode == 0
    try:
        os.kill(pid, signal.SIGKILL)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def start(host: str, port: int) -> int:
    record = load_pid_record()
    if valid_pid_record(record):
        record_host = str(record["host"])
        record_port = int(record["port"])
        instance = fetch_instance(record_host, record_port)
        if is_this_project(instance):
            print(
                f"服务已在运行：PID {instance['pid']}，"
                f"http://{probe_host(record_host)}:{record_port}"
            )
            return 0
        remove_pid_file()

    instance = fetch_instance(host, port)
    if is_this_project(instance):
        print(f"服务已在运行：PID {instance['pid']}，http://{probe_host(host)}:{port}")
        return 0
    if port_is_open(host, port):
        if is_legacy_project(host, port):
            fallback_port = find_available_port(host, port + 1)
            if fallback_port is None:
                print(f"启动失败：端口 {port} 被旧版实例占用，且未找到备用端口。")
                return 1
            print(f"端口 {port} 被无法接管的旧版实例占用，自动改用 {fallback_port}。")
            port = fallback_port
        else:
            print(f"启动失败：端口 {port} 已被其他进程占用。")
            return 1

    remove_pid_file()
    STDOUT_LOG.write_text("", encoding="utf-8")
    STDERR_LOG.write_text("", encoding="utf-8")

    with STDOUT_LOG.open("ab") as stdout, STDERR_LOG.open("ab") as stderr:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.launcher",
                "--host",
                host,
                "--port",
                str(port),
                "--pid-file",
                str(PID_FILE),
            ],
            cwd=ROOT_DIR,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            **process_detach_options(),
        )

    instance = wait_for_instance(host, port)
    if not instance:
        print("启动失败：服务未在 20 秒内就绪。")
        if STDERR_LOG.exists():
            tail = STDERR_LOG.read_text(encoding="utf-8", errors="replace")[-2000:]
            if tail.strip():
                print(tail)
        return 1

    print(f"启动成功：PID {instance['pid']}，端口 {port}")
    print(f"访问地址：http://{probe_host(host)}:{port}")
    print(f"标准日志：{STDOUT_LOG}")
    print(f"错误日志：{STDERR_LOG}")
    return 0


def stop(host: str, port: int) -> int:
    record = load_pid_record()
    if valid_pid_record(record):
        host = str(record["host"])
        port = int(record["port"])
    instance = fetch_instance(host, port)

    if is_this_project(instance):
        pids = {int(instance["pid"])}
    elif valid_pid_record(record) and int(record["port"]) == port:
        pids = {int(record["pid"])}
    elif is_legacy_project(host, port):
        pids = listener_pids(port)
        if not pids:
            print("停止失败：已识别为当前项目旧实例，但无法取得监听 PID。")
            return 1
    elif not port_is_open(host, port):
        remove_pid_file()
        print("服务未运行。")
        return 0
    else:
        print(f"停止失败：端口 {port} 上不是可识别的当前项目实例。")
        print("为避免误杀其他程序，控制器已拒绝停止该进程。")
        return 1

    stopped_pids = []
    denied_pids = []
    for pid in sorted(pids):
        try:
            os.kill(pid, signal.SIGTERM)
            stopped_pids.append(pid)
        except ProcessLookupError:
            continue
        except PermissionError:
            denied_pids.append(pid)

    if wait_for_port_close(host, port, timeout=8):
        remove_pid_file()
        pids_text = ", ".join(str(pid) for pid in stopped_pids) or "已退出"
        print(f"停止成功：PID {pids_text}")
        return 0

    forced_pids = [pid for pid in stopped_pids if force_terminate_process_tree(pid)]
    if forced_pids and wait_for_port_close(host, port, timeout=5):
        remove_pid_file()
        pids_text = ", ".join(str(pid) for pid in forced_pids)
        print(f"停止成功（超时后已结束进程树）：PID {pids_text}")
        return 0

    denied_text = f"；无权限 PID：{', '.join(map(str, denied_pids))}" if denied_pids else ""
    print(f"停止失败：端口 {port} 在超时后仍被占用{denied_text}。")
    return 1


def status(host: str, port: int) -> int:
    record = load_pid_record()
    if valid_pid_record(record):
        record_host = str(record["host"])
        record_port = int(record["port"])
        instance = fetch_instance(record_host, record_port)
        if is_this_project(instance):
            print(
                f"运行中：PID {instance['pid']}，"
                f"http://{probe_host(record_host)}:{record_port}"
            )
            return 0

    instance = fetch_instance(host, port)
    if is_this_project(instance):
        print(f"运行中：PID {instance['pid']}，http://{probe_host(host)}:{port}")
        return 0
    if is_legacy_project(host, port):
        pids = ", ".join(str(pid) for pid in sorted(listener_pids(port))) or "未知"
        print(f"运行中（旧版实例）：PID {pids}，http://{probe_host(host)}:{port}")
        return 2
    if port_is_open(host, port):
        print(f"端口 {port} 已占用，但不是可识别的当前项目实例。")
        return 2
    print("未运行。")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "start":
        return start(args.host, args.port)
    if args.command == "stop":
        return stop(args.host, args.port)
    if args.command == "restart":
        stopped = stop(args.host, args.port)
        return start(args.host, args.port) if stopped == 0 else stopped
    return status(args.host, args.port)


if __name__ == "__main__":
    raise SystemExit(main())
