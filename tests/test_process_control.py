from __future__ import annotations

import json

import radar
import start_services
import stop_services
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


def test_start_services_layout_is_valid():
    assert start_services.validate_project_layout() == []


def test_start_services_default_host_is_public():
    assert start_services.parse_args([]).host == "0.0.0.0"


def test_start_services_main_runs_radar_directly(monkeypatch):
    calls = []

    monkeypatch.setattr(
        start_services,
        "run_radar",
        lambda command, host, port: calls.append((command, host, port)) or 0,
    )

    assert start_services.main(["--restart", "--host", "127.0.0.1", "--port", "8040"]) == 0
    assert calls == [("restart", "127.0.0.1", 8040)]


def test_stop_services_reports_missing_venv(monkeypatch, tmp_path, capsys):
    missing_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    monkeypatch.setattr(stop_services, "venv_python", lambda: missing_python)

    assert stop_services.run_stop("127.0.0.1", 8030) == 1
    assert "未找到虚拟环境 Python" in capsys.readouterr().out
