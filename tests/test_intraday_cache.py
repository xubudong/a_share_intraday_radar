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
    service.history_attempted_at = {"000636": 118.0}
    service.save_cache()

    loaded = RadarService()

    assert loaded.intraday["000636"] == [10.0, 10.2]
    assert loaded.intraday_loaded_at["000636"] == 123.0
    assert loaded.intraday_attempted_at["000636"] == 120.0
    assert loaded.history_attempted_at["000636"] == 118.0


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


def test_daily_kline_refresh_batches_and_saves(monkeypatch):
    service = RadarService.__new__(RadarService)
    service.klines = {}
    service.history_loaded_at = {}
    service.history_attempted_at = {}
    service.errors = []
    stocks = [
        SimpleNamespace(code=f"00000{index}", name=f"测试{index}")
        for index in range(5)
    ]
    calls = []
    saves = []

    monkeypatch.setattr(service_module, "HISTORY_BATCH_SIZE", 2)
    monkeypatch.setattr(service_module, "FETCH_WORKERS", 1)
    monkeypatch.setattr(service_module, "service_log", lambda message: None)
    monkeypatch.setattr(
        service_module,
        "fetch_daily_klines",
        lambda code: calls.append(code) or [{"date": "2026-08-04", "close": 10.0}],
    )
    service.save_cache = lambda: saves.append(len(service.klines))

    service._refresh_daily_klines(stocks, force_history=True)

    assert calls == ["000000", "000001", "000002", "000003", "000004"]
    assert saves == [2, 4, 5]
    assert set(service.klines) == set(calls)
    assert set(service.history_attempted_at) == set(calls)


def test_normal_refresh_only_fetches_missing_history():
    service = RadarService.__new__(RadarService)
    service.pool = [
        SimpleNamespace(code="000001"),
        SimpleNamespace(code="000002"),
        SimpleNamespace(code="000003"),
    ]
    service.klines = {
        "000001": [{"date": "2026-08-01", "close": 10.0}],
        "000002": [],
    }
    now = service_module.time.time()
    service.history_attempted_at = {"000002": now}

    normal = service.stocks_requiring_history(False)
    forced = service.stocks_requiring_history(True)

    assert [stock.code for stock in normal] == ["000003"]
    assert [stock.code for stock in forced] == ["000001", "000002", "000003"]
