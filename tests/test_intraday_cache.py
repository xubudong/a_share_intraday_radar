from types import SimpleNamespace

import app.service as service_module
from app.service import RadarService


def test_intraday_cache_survives_service_reload(tmp_path, monkeypatch):
    cache_path = tmp_path / "state_cache.json"
    monkeypatch.setattr(service_module, "CACHE_PATH", cache_path)
    service = RadarService()
    service.intraday = {"000636": [10.0, 10.2]}
    service.intraday_loaded_at = {"000636": 123.0}
    service.intraday_attempted_at = {"000636": 120.0}
    service.save_cache()

    loaded = RadarService()

    assert loaded.intraday["000636"] == [10.0, 10.2]
    assert loaded.intraday_loaded_at["000636"] == 123.0
    assert loaded.intraday_attempted_at["000636"] == 120.0


def test_intraday_refresh_limits_batch_and_keeps_recent_data(monkeypatch):
    service = RadarService.__new__(RadarService)
    service.pool = [
        SimpleNamespace(code="000001"),
        SimpleNamespace(code="000002"),
        SimpleNamespace(code="000003"),
        SimpleNamespace(code="000004"),
    ]
    service.intraday = {"000001": [9.9, 10.0]}
    service.intraday_loaded_at = {"000001": service_module.time.time()}
    service.intraday_attempted_at = {}
    calls = []

    monkeypatch.setattr(service_module, "INTRADAY_MAX_PER_REFRESH", 2)
    monkeypatch.setattr(
        service_module,
        "fetch_intraday_trends",
        lambda code: calls.append(code) or [10.0, 10.1],
    )

    service._refresh_intraday()

    assert "000001" not in calls
    assert set(calls) == {"000002", "000003"}
    assert len(calls) == 2
    assert service.intraday["000001"] == [9.9, 10.0]
