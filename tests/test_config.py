import threading
import time

from app.config import StarStore, load_stock_pool, star_store


def test_stock_pool_loads_and_deduplicates_duplicate_codes():
    pool = load_stock_pool()
    codes = [stock.code for stock in pool]

    assert "000636" in codes
    assert "603002" in codes
    assert len(codes) == len(set(codes))

    # 晶瑞电材(300655) appears in both 光刻胶 and 湿电子 — groups should merge
    jingrui = next((stock for stock in pool if stock.code == "300655"), None)
    assert jingrui is not None
    assert len(jingrui.groups) >= 2
    assert "半导体材料-光刻胶" in jingrui.groups
    assert "半导体材料-湿电子" in jingrui.groups


def test_requested_sector_groups_and_tiers_are_present():
    pool = load_stock_pool()
    stocks_by_code = {stock.code: stock for stock in pool}
    groups = {group for stock in pool for group in stock.groups}

    assert "300476" in stocks_by_code
    assert stocks_by_code["300476"].name == "胜宏科技"
    assert stocks_by_code["300476"].group == "PCB"
    assert stocks_by_code["300476"].tier == 1
    assert "002962" not in stocks_by_code

    expected_groups = {
        "化工-磷化工",
        "化工-氟化工",
        "化工-纯碱氯碱",
        "化工-煤化工",
        "化工-钛白粉",
        "有色-铜",
        "有色-贵金属",
        "有色-镍",
        "有色-锂矿",
        "有色-钴",
        "有色-钨",
        "有色-锡锑",
        "有色-钼",
        "有色-稀缺资源",
        "有色-稀土资源",
        "有色-稀土永磁",
        "半导体芯片-AI芯片",
        "半导体芯片-设计",
        "半导体芯片-晶圆制造",
        "半导体芯片-设备",
        "半导体芯片-功率器件",
        "光模块-整机",
        "光模块-上游光器件",
        "光模块-CPO硅光",
        "新能源-锂电设备",
        "新能源-锂电电芯/储能",
        "新能源-锂电材料-正极",
        "新能源-锂电材料-负极",
        "新能源-锂电材料-隔膜",
        "新能源-锂电材料-电解液",
        "新能源-锂电材料-铜箔/复合集流体",
        "新能源-锂电材料-铝箔/结构件",
        "新能源-锂电回收/前驱体",
        "新能源-锂电新技术-固态/半固态",
        "机器人核心",
        "液冷核心",
    }
    assert expected_groups <= groups

    assert stocks_by_code["002895"].tier == 2
    assert {"有色-镍", "有色-钴"} <= set(stocks_by_code["603799"].groups)
    assert {"半导体芯片-AI芯片", "半导体芯片-设计"} <= set(
        stocks_by_code["300474"].groups
    )
    assert {"光模块-上游光器件", "光模块-CPO硅光"} <= set(
        stocks_by_code["300394"].groups
    )
    assert stocks_by_code["300450"].tier == 1
    assert stocks_by_code["688006"].tier == 1
    assert stocks_by_code["301325"].group == "新能源-锂电设备"
    assert stocks_by_code["300750"].tier == 1
    assert stocks_by_code["300769"].group == "新能源-锂电材料-正极"
    assert stocks_by_code["002812"].group == "新能源-锂电材料-隔膜"
    assert stocks_by_code["002709"].group == "新能源-锂电材料-电解液"
    assert {"新能源-锂电设备", "新能源-锂电新技术-固态/半固态"} <= set(
        stocks_by_code["300450"].groups
    )
    assert {"铜箔", "新能源-锂电材料-铜箔/复合集流体"} <= set(stocks_by_code["301217"].groups)
    assert {"有色-镍", "有色-钴", "新能源-锂电回收/前驱体"} <= set(
        stocks_by_code["603799"].groups
    )
    assert {
        "300124",
        "002747",
        "002050",
        "601689",
        "688017",
        "002472",
        "603728",
        "603667",
        "603662",
        "688322",
    } <= set(stocks_by_code)
    assert stocks_by_code["688017"].group == "机器人核心"
    assert stocks_by_code["688017"].tier == 1
    assert stocks_by_code["688322"].tier == 2
    assert {
        "002837",
        "301018",
        "872808",
        "300499",
        "300602",
        "300547",
        "300684",
        "300990",
        "603912",
        "301202",
    } <= set(stocks_by_code)
    assert stocks_by_code["002837"].group == "液冷核心"
    assert stocks_by_code["872808"].tier == 1
    assert stocks_by_code["301202"].tier == 2


def test_duplicate_stock_keeps_highest_priority_tier():
    pool = load_stock_pool()
    xingfa = next(stock for stock in pool if stock.code == "600141")

    assert xingfa.tier == 1


def test_star_store_basic():
    """Star store should support is_starred and toggle."""
    # Verify toggle on/off works
    assert star_store.toggle("999998") is True
    assert star_store.is_starred("999998")
    assert star_store.toggle("999998") is False
    assert not star_store.is_starred("999998")
    # Verify a non-existent code is not starred
    assert not star_store.is_starred("999997")


def test_star_toggle():
    # Toggle a code on
    assert star_store.toggle("999999") is True
    assert star_store.is_starred("999999")
    # Toggle it off
    assert star_store.toggle("999999") is False
    assert not star_store.is_starred("999999")


def test_star_store_supports_group_stars(tmp_path):
    path = tmp_path / "star_state.json"
    path.write_text('{"stars": [], "groups": []}', encoding="utf-8")
    store = StarStore(path)

    assert store.group_count == 0
    assert not store.is_group_starred("机器人核心")
    assert store.toggle_group("机器人核心") is True
    assert store.is_group_starred("机器人核心")
    assert store.group_count == 1

    reloaded = StarStore(path)
    assert reloaded.is_group_starred("机器人核心")
    assert reloaded.toggle_group("机器人核心") is False
    assert not reloaded.is_group_starred("机器人核心")


def test_snapshot_save_and_load():
    from app.service import radar_service
    # Save a snapshot
    sid = radar_service.save_snapshot()
    assert sid  # non-empty id
    # List snapshots
    snaps = radar_service.list_snapshots()
    assert any(s["id"] == sid for s in snaps)
    # Load the snapshot
    data = radar_service.load_snapshot(sid)
    assert data is not None
    assert data["id"] == sid
    assert "stocks" in data
    # Non-existent snapshot
    assert radar_service.load_snapshot("nonexistent") is None


def test_dashboard_counts_stock_in_each_of_its_groups():
    from app.service import RadarService

    service = RadarService.__new__(RadarService)
    service._refresh_state_lock = threading.RLock()
    service._refreshing = False
    service._pending_force_history = False
    service.pool = [object()]
    service.stocks = [
        {
            "code": "603799",
            "group": "有色-镍",
            "groups": ["有色-镍", "有色-钴"],
            "quote": {"pct_chg": 2.5},
            "signal": {"signal": "观察"},
        }
    ]
    service.errors = []
    service.last_refresh_at = None
    service.last_success_at = None
    service.last_refresh_mode = "none"

    dashboard = service.dashboard()

    assert dashboard["group_stats"]["有色-镍"]["total"] == 1
    assert dashboard["group_stats"]["有色-钴"]["total"] == 1
    assert dashboard["group_stats"]["有色-镍"]["avg_pct"] == 2.5
    assert dashboard["group_stats"]["有色-钴"]["avg_pct"] == 2.5


def test_dashboard_marks_starred_groups(monkeypatch):
    from app import service as service_module
    from app.service import RadarService

    class FakeStarStore:
        count = 0
        group_count = 1

        def is_group_starred(self, group):
            return group == "机器人核心"

    monkeypatch.setattr(service_module, "star_store", FakeStarStore())

    service = RadarService.__new__(RadarService)
    service._refresh_state_lock = threading.RLock()
    service._refreshing = False
    service._pending_force_history = False
    service.pool = [object()]
    service.stocks = [
        {
            "code": "688017",
            "group": "机器人核心",
            "groups": ["机器人核心"],
            "tier": 1,
            "quote": {"pct_chg": 1.5},
            "signal": {"signal": "观察"},
        }
    ]
    service.errors = []
    service.last_refresh_at = None
    service.last_success_at = None
    service.last_refresh_mode = "none"

    dashboard = service.dashboard()

    assert dashboard["summary"]["group_stars"] == 1
    assert dashboard["group_stats"]["机器人核心"]["star"] is True


def test_dashboard_reports_average_pct_by_tier():
    from app.service import RadarService

    service = RadarService.__new__(RadarService)
    service._refresh_state_lock = threading.RLock()
    service._refreshing = False
    service._pending_force_history = False
    service.pool = [object(), object(), object(), object()]
    service.stocks = [
        {
            "code": "600001",
            "group": "测试",
            "groups": ["测试"],
            "tier": 1,
            "quote": {"pct_chg": 3.0},
            "signal": {"signal": "观察"},
        },
        {
            "code": "600002",
            "group": "测试",
            "groups": ["测试"],
            "tier": 1,
            "quote": {"pct_chg": 1.0},
            "signal": {"signal": "观察"},
        },
        {
            "code": "600003",
            "group": "测试",
            "groups": ["测试"],
            "tier": 2,
            "quote": {"pct_chg": -2.0},
            "signal": {"signal": "观察"},
        },
        {
            "code": "600004",
            "group": "测试",
            "groups": ["测试"],
            "tier": 3,
            "quote": {},
            "signal": {"signal": "观察"},
        },
    ]
    service.errors = []
    service.last_refresh_at = None
    service.last_success_at = None
    service.last_refresh_mode = "none"

    summary = service.dashboard()["summary"]

    assert summary["avg_pct_t1"] == 2.0
    assert summary["avg_pct_t2"] == -2.0
    assert summary["avg_pct_t3"] is None


def test_dashboard_includes_market_indices():
    from app.service import RadarService

    service = RadarService.__new__(RadarService)
    service._refresh_state_lock = threading.RLock()
    service._refreshing = False
    service._pending_force_history = False
    service.pool = []
    service.stocks = []
    service.errors = []
    service.market_indices = [
        {
            "code": "000001",
            "name": "上证指数",
            "price": 4098.85,
            "pct_chg": 0.06,
            "change": 2.38,
            "intraday": [4094.21, 4099.22, 4098.85],
        }
    ]
    service.last_refresh_at = None
    service.last_success_at = None
    service.last_refresh_mode = "none"

    dashboard = service.dashboard()

    assert dashboard["market_indices"][0]["name"] == "上证指数"
    assert dashboard["market_indices"][0]["intraday"] == [4094.21, 4099.22, 4098.85]


def test_background_refresh_coalesces_duplicate_requests():
    from app.service import RadarService

    service = RadarService()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fake_refresh(force_history=False):
        calls.append(force_history)
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=2)
        return {}

    service.refresh = fake_refresh

    first = service.start_refresh(force_history=False)
    assert entered.wait(timeout=2)
    duplicate = service.start_refresh(force_history=False)
    queued_history = service.start_refresh(force_history=True)

    assert first["accepted"] is True
    assert duplicate["accepted"] is False
    assert queued_history["accepted"] is False
    assert queued_history["pending_force_history"] is True

    refresh_thread = service._refresh_thread
    release.set()
    refresh_thread.join(timeout=2)

    assert calls == [False, True]
    assert service.refresh_status()["refreshing"] is False
    assert service.refresh_status()["pending_force_history"] is False


def test_refresh_api_returns_immediately_while_worker_is_running(monkeypatch):
    from fastapi.testclient import TestClient

    from app.server import app
    from app.service import radar_service

    entered = threading.Event()
    release = threading.Event()

    def fake_refresh(force_history=False):
        entered.set()
        assert release.wait(timeout=3)
        return {}

    monkeypatch.setattr(radar_service, "refresh", fake_refresh)
    radar_service._refreshing = False
    radar_service._pending_force_history = False
    radar_service._refresh_thread = None

    with TestClient(app) as client:
        assert entered.wait(timeout=2)

        started = time.perf_counter()
        normal = client.post("/api/refresh?force_history=false")
        normal_elapsed = time.perf_counter() - started
        history = client.post("/api/refresh?force_history=true")

        assert normal.status_code == 200
        assert normal.json()["accepted"] is False
        assert normal_elapsed < 1
        assert history.status_code == 200
        assert history.json()["pending_force_history"] is True

        refresh_thread = radar_service._refresh_thread
        release.set()
        refresh_thread.join(timeout=3)
