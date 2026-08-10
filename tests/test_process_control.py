from __future__ import annotations

import json
from pathlib import Path

import manage as radar
from app.instance import APP_ID, root_fingerprint


def test_instance_endpoint_identifies_current_project():
    from fastapi.testclient import TestClient

    from app.config import ROOT_DIR
    from app.server import app
    from app.service import radar_service

    original_start_refresh = radar_service.start_refresh
    radar_service.start_refresh = lambda force_history=False: {
        "accepted": False,
        "refreshing": False,
    }
    try:
        with TestClient(app) as client:
            response = client.get("/api/instance")
    finally:
        radar_service.start_refresh = original_start_refresh

    assert response.status_code == 200
    payload = response.json()
    assert payload["app_id"] == APP_ID
    assert payload["root_fingerprint"] == root_fingerprint(ROOT_DIR)
    assert isinstance(payload["pid"], int)


def test_stop_refuses_unrecognized_process(monkeypatch, capsys):
    monkeypatch.setattr(radar, "fetch_instance", lambda host, port: None)
    monkeypatch.setattr(radar, "load_pid_record", lambda: None)
    monkeypatch.setattr(radar, "is_legacy_project", lambda host, port: False)
    monkeypatch.setattr(radar, "port_is_open", lambda host, port: True)

    assert radar.stop("127.0.0.1", 8030) == 1
    assert "拒绝停止" in capsys.readouterr().out


def test_stop_recovers_managed_instance_without_pid_file(monkeypatch):
    instance = {
        "app_id": APP_ID,
        "pid": 43210,
        "root_fingerprint": root_fingerprint(radar.ROOT_DIR),
    }
    port_states = iter((True, False))
    killed = []

    monkeypatch.setattr(radar, "fetch_instance", lambda host, port: instance)
    monkeypatch.setattr(radar, "load_pid_record", lambda: None)
    monkeypatch.setattr(radar, "port_is_open", lambda host, port: next(port_states))
    monkeypatch.setattr(radar.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(radar, "remove_pid_file", lambda: None)

    assert radar.stop("127.0.0.1", 8030) == 0
    assert killed == [(43210, radar.signal.SIGTERM)]


def test_stop_recovers_legacy_project_by_cache_path(monkeypatch):
    port_states = iter((True, False))
    killed = []

    monkeypatch.setattr(radar, "fetch_instance", lambda host, port: None)
    monkeypatch.setattr(radar, "load_pid_record", lambda: None)
    monkeypatch.setattr(radar, "is_legacy_project", lambda host, port: True)
    monkeypatch.setattr(radar, "listener_pids", lambda port: {111, 222})
    monkeypatch.setattr(radar, "port_is_open", lambda host, port: next(port_states))
    monkeypatch.setattr(radar.os, "kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(radar, "remove_pid_file", lambda: None)

    assert radar.stop("127.0.0.1", 8030) == 0
    assert killed == [111, 222]


def test_load_pid_record_rejects_invalid_json(monkeypatch, tmp_path):
    pid_file = tmp_path / ".radar.pid"
    pid_file.write_text("not-json", encoding="ascii")
    monkeypatch.setattr(radar, "PID_FILE", pid_file)

    assert radar.load_pid_record() is None

    pid_file.write_text(json.dumps({"pid": 123}), encoding="ascii")
    assert radar.load_pid_record() == {"pid": 123}


def test_find_available_port_skips_occupied_ports(monkeypatch):
    monkeypatch.setattr(
        radar,
        "port_is_open",
        lambda host, port: port in {8030, 8031},
    )

    assert radar.find_available_port("127.0.0.1", 8030) == 8032


def test_process_detach_options_use_new_session_on_linux(monkeypatch):
    monkeypatch.setattr(radar.os, "name", "posix")

    assert radar.process_detach_options() == {"start_new_session": True}


def test_force_terminate_uses_process_tree_on_windows(monkeypatch):
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(radar.os, "name", "nt")
    monkeypatch.setattr(
        radar.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)) or Result(),
    )

    assert radar.force_terminate_process_tree(43210) is True
    assert calls[0][0] == ["taskkill", "/PID", "43210", "/T", "/F"]


def test_manager_rejects_system_python(monkeypatch, tmp_path, capsys):
    expected = tmp_path / ".venv" / "Scripts" / "python.exe"
    expected.parent.mkdir(parents=True)
    expected.touch()
    monkeypatch.setattr(radar, "project_python", lambda: expected)
    monkeypatch.setattr(radar.sys, "executable", str(tmp_path / "python.exe"))

    assert radar.validate_runtime() is False
    assert "不属于项目 .venv" in capsys.readouterr().out


def test_root_launchers_use_unified_manager():
    root = Path(__file__).resolve().parents[1]

    start_ps1 = (root / "start.ps1").read_text(encoding="utf-8")
    stop_ps1 = (root / "stop.ps1").read_text(encoding="utf-8")
    start_sh = (root / "start.sh").read_text(encoding="utf-8")
    stop_sh = (root / "stop.sh").read_text(encoding="utf-8")

    assert ".venv\\Scripts\\pythonw.exe" in start_ps1
    assert "Start-Process" in start_ps1
    assert "-WindowStyle Hidden" in start_ps1
    assert "-Wait" not in start_ps1
    assert "$Manager stop @args" in stop_ps1
    assert '"$PROJECT_ROOT/manage.py" start "$@"' in start_sh
    assert '"$PROJECT_ROOT/manage.py" stop "$@"' in stop_sh


def test_hidden_launcher_uses_pythonw_without_terminal():
    launcher = Path(__file__).resolve().parents[1] / "start_hidden.vbs"
    content = launcher.read_text(encoding="ascii")

    assert "pythonw.exe" in content
    assert "manage.py" in content
    assert "powershell.exe" not in content
    assert "shell.Run command, 0, False" in content
