import json
from types import SimpleNamespace

import app.service as service_module
from app.history_store import DailyKlineStore
from app.service import RadarService


def test_intraday_cache_survives_service_reload(tmp_path, monkeypatch):
    cache_path = tmp_path / "state_cache.json"
    db_path = tmp_path / "radar.db"
    monkeypatch.setattr(service_module, "CACHE_PATH", cache_path)
    monkeypatch.setattr(service_module, "DB_PATH", db_path)
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


def test_legacy_klines_cache_migrates_to_sqlite(tmp_path, monkeypatch):
    cache_path = tmp_path / "state_cache.json"
    db_path = tmp_path / "radar.db"
    cache_path.write_text(
        json.dumps(
            {
                "quotes": {},
                "klines": {
                    "000001": [
                        {
                            "date": "2026-08-01",
                            "open": 9.5,
                            "close": 10.0,
                            "high": 10.2,
                            "low": 9.4,
                            "volume": 100,
                        }
                    ]
                },
                "last_success_at": "2026-08-04T10:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(service_module, "CACHE_PATH", cache_path)
    monkeypatch.setattr(service_module, "DB_PATH", db_path)
    monkeypatch.setattr(RadarService, "build_stocks", lambda self: [])

    service = RadarService()
    rows = service.history_store.get_rows("000001")
    saved_cache = json.loads(cache_path.read_text(encoding="utf-8"))

    assert rows[0]["close"] == 10.0
    assert service.last_success_at == "2026-08-04T10:00:00+08:00"
    assert "klines" not in saved_cache


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


def test_daily_kline_refresh_batches_and_saves(monkeypatch, tmp_path):
    service = RadarService.__new__(RadarService)
    service.history_store = DailyKlineStore(tmp_path / "radar.db")
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
    service.save_cache = lambda: saves.append(service.history_store.count_codes())

    service._refresh_daily_klines(stocks, force_history=True)

    assert calls == ["000000", "000001", "000002", "000003", "000004"]
    assert saves == [2, 4, 5]
    assert service.history_store.count_codes() == 5
    assert set(service.history_attempted_at) == set(calls)


def test_normal_refresh_only_fetches_missing_history(tmp_path):
    service = RadarService.__new__(RadarService)
    service.history_store = DailyKlineStore(tmp_path / "radar.db")
    service.pool = [
        SimpleNamespace(code="000001"),
        SimpleNamespace(code="000002"),
        SimpleNamespace(code="000003"),
    ]
    service.history_store.replace_rows(
        "000001",
        [{"date": "2026-08-01", "close": 10.0}],
    )
    now = service_module.time.time()
    service.history_attempted_at = {"000002": now}

    normal = service.stocks_requiring_history(False)
    forced = service.stocks_requiring_history(True)

    assert [stock.code for stock in normal] == ["000003"]
    assert [stock.code for stock in forced] == ["000001", "000002", "000003"]


def test_quote_refresh_only_enqueues_history(monkeypatch, tmp_path):
    service = RadarService.__new__(RadarService)
    service._lock = service_module.threading.Lock()
    service._refresh_state_lock = service_module.threading.RLock()
    service._refreshing = False
    service._pending_force_history = False
    service._history_state_lock = service_module.threading.RLock()
    service._history_refreshing = False
    service._history_force_pending = False
    service._history_total = 0
    service._history_completed = 0
    service._history_updated = 0
    service._history_failed = 0
    service._history_started_at = None
    service._history_finished_at = None
    service._history_snapshot_pending = False
    service._history_thread = None
    service.pool = [SimpleNamespace(code="000001", name="测试", groups=["测试"])]
    service.quotes = {}
    service.history_store = DailyKlineStore(tmp_path / "radar.db")
    service.intraday = {}
    service.intraday_loaded_at = {}
    service.intraday_attempted_at = {}
    service.market_indices = []
    service.history_loaded_at = {}
    service.history_attempted_at = {}
    service.errors = []
    service.stocks = []
    service.last_refresh_at = None
    service.last_success_at = None
    service.last_refresh_mode = "none"
    enqueued = []

    monkeypatch.setattr(service_module, "load_stock_pool", lambda: service.pool)
    monkeypatch.setattr(
        service_module,
        "fetch_realtime_quotes",
        lambda codes: {"000001": {"price": 10.0}},
    )
    service._refresh_market_indices = lambda: None
    service._refresh_intraday = lambda: None
    service.build_stocks = lambda: [
        {
            "code": "000001",
            "group": "测试",
            "groups": ["测试"],
            "quote": {"pct_chg": 1.0},
            "signal": {"signal": "观察"},
        }
    ]
    service.save_cache = lambda: None
    service.start_history_refresh = lambda **kwargs: enqueued.append(kwargs) or {
        "accepted": True
    }

    service.refresh(force_history=False)

    assert enqueued == [{"force_history": False, "save_snapshot": False}]


def test_running_history_force_request_does_not_requeue_quote_refresh(tmp_path):
    service = RadarService.__new__(RadarService)
    service._refresh_state_lock = service_module.threading.RLock()
    service._refreshing = False
    service._pending_force_history = False
    service._history_state_lock = service_module.threading.RLock()
    service._history_refreshing = True
    service._history_force_pending = False
    service._history_snapshot_pending = False
    service._history_total = 3
    service._history_completed = 1
    service._history_updated = 1
    service._history_failed = 0
    service._history_started_at = "2026-08-04T10:00:00+08:00"
    service._history_finished_at = None
    service.history_store = DailyKlineStore(tmp_path / "radar.db")
    service.pool = [SimpleNamespace(code="000001")]
    service.last_refresh_mode = "auto"

    status = service.start_history_refresh(force_history=True, save_snapshot=True)
    refresh_status = service.refresh_status()

    assert status["accepted"] is False
    assert status["pending_force"] is True
    assert service._pending_force_history is False
    assert refresh_status["pending_force_history"] is True
