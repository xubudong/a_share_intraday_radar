import json

from fastapi.testclient import TestClient

import app.service as service_module
from app.server import app
from app.service import RadarService, radar_service


def test_delete_snapshot_removes_only_valid_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(service_module, "SNAPSHOTS_DIR", tmp_path)
    snapshot_id = "20260611T223000"
    snapshot = tmp_path / f"{snapshot_id}.json"
    snapshot.write_text(json.dumps({"id": snapshot_id}), encoding="utf-8")
    service = RadarService.__new__(RadarService)

    assert service.delete_snapshot(snapshot_id) is True
    assert not snapshot.exists()
    assert service.delete_snapshot(snapshot_id) is False
    assert service.delete_snapshot("../state_cache") is False


def test_delete_snapshot_api_returns_success_and_not_found(monkeypatch):
    original_start_refresh = radar_service.start_refresh
    radar_service.start_refresh = lambda force_history=False: {
        "accepted": False,
        "refreshing": False,
    }
    monkeypatch.setattr(
        radar_service,
        "delete_snapshot",
        lambda snapshot_id: snapshot_id == "20260611T223000",
    )
    try:
        with TestClient(app) as client:
            deleted = client.delete("/api/snapshots/20260611T223000")
            missing = client.delete("/api/snapshots/20260611T223001")
    finally:
        radar_service.start_refresh = original_start_refresh

    assert deleted.status_code == 200
    assert deleted.json() == {"id": "20260611T223000", "deleted": True}
    assert missing.status_code == 404
