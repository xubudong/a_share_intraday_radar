import threading
import time

from app.config import CONFIG_PATH, StarStore, load_stock_pool, star_store


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
    assert stocks_by_code["300476"].group == "电子元件-PCB"
    assert stocks_by_code["300476"].tier == 1
    assert "002962" not in stocks_by_code
    assert stocks_by_code["600105"].group == "光通信-光材料/光纤光缆"
    assert stocks_by_code["600105"].tier == 3

    assert stocks_by_code["000636"].group == "电子元件-MLCC/被动元件"
    assert stocks_by_code["603773"].group == "电子元件-玻璃基板"
    assert stocks_by_code["603256"].group == "电子元件-玻璃玻纤/电子布"
    assert stocks_by_code["301217"].group == "电子元件-电子铜箔"
    assert stocks_by_code["600183"].group == "电子元件-覆铜板"
    assert stocks_by_code["603986"].group == "半导体芯片-存储"
    assert stocks_by_code["600584"].group == "先进封装-封测厂"
    assert stocks_by_code["002371"].group == "半导体设备-前道核心设备"

    expected_groups = {
        "电子元件-MLCC/被动元件",
        "电子元件-玻璃基板",
        "电子元件-玻璃玻纤/电子布",
        "电子元件-PCB",
        "电子元件-电子铜箔",
        "电子元件-覆铜板",
        "化工-工业气体",
        "半导体芯片-存储",
        "先进封装-封测厂",
        "化工-磷化工",
        "化工-氟化工",
        "化工-纯碱氯碱",
        "化工-煤化工",
        "化工-钛白粉",
        "化工-电子树脂/合成树脂",
        "有色-铜",
        "有色-铝",
        "有色-贵金属",
        "有色-镍",
        "有色-锂矿",
        "有色-钴",
        "有色-钨",
        "有色-锡锑",
        "有色-钼",
        "有色-稀缺资源",
        "有色-镓锗铟",
        "有色-稀土资源",
        "有色-稀土永磁",
        "半导体材料-CMP/抛光材料",
        "半导体芯片-AI芯片",
        "半导体芯片-设计",
        "半导体芯片-晶圆制造",
        "半导体设备-前道核心设备",
        "半导体芯片-功率器件",
        "半导体芯片-端侧AI/AIoT",
        "半导体芯片-CIS/视觉感知",
        "半导体芯片-模拟/RF/PMIC",
        "半导体芯片-功率/电源管理",
        "半导体芯片-IP/FPGA/ASIC",
        "半导体芯片-网络通信",
        "半导体设备-检测/量测",
        "半导体设备-零部件/工艺系统",
        "半导体设备-光刻/涂胶显影配套",
        "光通信-光芯片",
        "光通信-光器件/光引擎",
        "光通信-光材料/光纤光缆",
        "光通信-光模块整机",
        "光通信-CPO/硅光",
        "光通信-高速连接/网络设备",
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
        "机器人-本体/核心零部件",
        "算力基础设施-液冷",
        "电网设备-二次设备/数字电网",
        "电网设备-特高压/一次设备",
        "电网设备-变压器/配电",
        "电网设备-智能电表/用电侧",
        "国产算力-服务器整机",
        "国产算力-高速网络/交换设备",
        "国产算力-IDC/数据中心运营",
        "国产算力-电源/UPS",
        "国产算力-基础软件",
        "国产算力-数据库/中间件",
        "国产算力-边缘终端/AI硬件",
        "数据安全-网络安全",
        "数据安全-数据服务/AI数据",
        "计算机软件-办公/企业智能体",
        "计算机软件-企业软件/工业软件",
        "计算机软件-搜索/知识管理",
        "计算机软件-教育信息化/AI教育",
        "计算机软件-政务/医疗IT",
        "计算机软件-金融IT",
        "传媒-营销广告",
        "传媒-IP/语料/版权",
        "传媒-影视内容",
        "游戏-AI游戏/互动娱乐",
        "大金融-证券",
        "大金融-银行",
        "大金融-保险",
        "消费-白酒/食品饮料",
        "消费-家电",
        "消费-零售/免税",
        "消费-旅游酒店",
        "地产链-开发/物业",
        "地产链-家居/建材",
        "红利资产-煤炭",
        "红利资产-电力/公用事业",
        "交通运输-航运/港口",
        "交通运输-航空机场/快递",
        "农业-养殖/饲料",
        "农业-种业/粮食",
        "建筑建材-水泥/玻璃",
        "建筑建材-基建央企",
        "石油石化-油气开采/油服",
        "石油石化-炼化/化纤",
        "医药-创新药",
        "医药-中药",
        "医药-血制品",
        "医药-疫苗",
        "医药-原料药",
        "医药-CXO",
        "医药-医疗器械",
        "医药-IVD",
        "医药-医疗服务",
        "医药-药店/医药商业",
        "医药-医美",
        "医药-生命科学上游",
    }
    assert expected_groups <= groups

    assert stocks_by_code["002895"].tier == 2
    assert {"有色-镍", "有色-钴"} <= set(stocks_by_code["603799"].groups)
    assert {"半导体芯片-AI芯片", "半导体芯片-设计"} <= set(
        stocks_by_code["300474"].groups
    )
    assert {"光通信-光器件/光引擎", "光通信-CPO/硅光"} <= set(
        stocks_by_code["300394"].groups
    )
    assert stocks_by_code["688498"].group == "光通信-光芯片"
    assert stocks_by_code["688048"].group == "光通信-光芯片"
    assert stocks_by_code["002222"].group == "光通信-光材料/光纤光缆"
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
    assert {"电子元件-电子铜箔", "新能源-锂电材料-铜箔/复合集流体"} <= set(stocks_by_code["301217"].groups)
    assert {"有色-镍", "有色-钴", "新能源-锂电回收/前驱体"} <= set(
        stocks_by_code["603799"].groups
    )
    assert stocks_by_code["601609"].group == "有色-铜"
    assert stocks_by_code["601600"].group == "有色-铝"
    assert {"有色-铝", "有色-镓锗铟"} <= set(stocks_by_code["601600"].groups)
    assert stocks_by_code["601020"].group == "有色-锡锑"
    assert stocks_by_code["600961"].group == "有色-镓锗铟"
    assert stocks_by_code["688019"].group == "半导体材料-CMP/抛光材料"
    assert stocks_by_code["605589"].group == "化工-电子树脂/合成树脂"
    assert stocks_by_code["300236"].group == "半导体材料-湿电子"
    assert stocks_by_code["603893"].group == "半导体芯片-端侧AI/AIoT"
    assert stocks_by_code["603501"].group == "半导体芯片-CIS/视觉感知"
    assert stocks_by_code["688052"].group == "半导体芯片-模拟/RF/PMIC"
    assert stocks_by_code["688396"].group == "半导体芯片-功率/电源管理"
    assert stocks_by_code["688521"].group == "半导体芯片-IP/FPGA/ASIC"
    assert stocks_by_code["688515"].group == "半导体芯片-网络通信"
    assert stocks_by_code["688361"].group == "半导体设备-检测/量测"
    assert stocks_by_code["688409"].group == "半导体设备-零部件/工艺系统"
    assert stocks_by_code["688037"].group == "半导体设备-光刻/涂胶显影配套"
    assert stocks_by_code["300548"].group == "光通信-光器件/光引擎"
    assert stocks_by_code["300913"].group == "光通信-高速连接/网络设备"
    assert {"半导体芯片-端侧AI/AIoT", "半导体芯片-CIS/视觉感知"} <= set(
        stocks_by_code["300613"].groups
    )
    assert {"半导体芯片-模拟/RF/PMIC", "半导体芯片-功率/电源管理"} <= set(
        stocks_by_code["688508"].groups
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
    assert stocks_by_code["688017"].group == "机器人-本体/核心零部件"
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
    assert stocks_by_code["002837"].group == "算力基础设施-液冷"
    assert stocks_by_code["872808"].tier == 1
    assert stocks_by_code["301202"].tier == 2
    assert {
        "600406",
        "000400",
        "002028",
        "600312",
        "601179",
        "601126",
        "600089",
        "688676",
        "603556",
        "300360",
    } <= set(stocks_by_code)
    assert stocks_by_code["600406"].group == "电网设备-二次设备/数字电网"
    assert stocks_by_code["600312"].group == "电网设备-特高压/一次设备"
    assert stocks_by_code["688676"].group == "电网设备-变压器/配电"
    assert stocks_by_code["603556"].group == "电网设备-智能电表/用电侧"
    assert {
        "电网设备-二次设备/数字电网",
        "电网设备-特高压/一次设备",
    } <= set(stocks_by_code["000400"].groups)
    assert {
        "电网设备-特高压/一次设备",
        "电网设备-变压器/配电",
    } <= set(stocks_by_code["002028"].groups)
    assert stocks_by_code["600089"].tier == 1
    assert stocks_by_code["603019"].group == "国产算力-服务器整机"
    assert stocks_by_code["000063"].group == "国产算力-高速网络/交换设备"
    assert stocks_by_code["603881"].group == "国产算力-IDC/数据中心运营"
    assert stocks_by_code["002335"].group == "国产算力-电源/UPS"
    assert stocks_by_code["600536"].group == "国产算力-基础软件"
    assert stocks_by_code["002368"].group == "国产算力-数据库/中间件"
    assert stocks_by_code["688561"].group == "数据安全-网络安全"
    assert stocks_by_code["688475"].group == "国产算力-边缘终端/AI硬件"
    assert {"国产算力-服务器整机", "国产算力-高速网络/交换设备"} <= set(
        stocks_by_code["000938"].groups
    )
    assert {"半导体芯片-网络通信", "国产算力-高速网络/交换设备"} <= set(
        stocks_by_code["688702"].groups
    )
    assert {"国产算力-IDC/数据中心运营", "国产算力-数据库/中间件"} <= set(
        stocks_by_code["600845"].groups
    )
    assert stocks_by_code["600588"].group == "计算机软件-办公/企业智能体"
    assert stocks_by_code["300170"].group == "计算机软件-企业软件/工业软件"
    assert stocks_by_code["300229"].group == "计算机软件-搜索/知识管理"
    assert stocks_by_code["000526"].group == "计算机软件-教育信息化/AI教育"
    assert stocks_by_code["603108"].group == "计算机软件-政务/医疗IT"
    assert stocks_by_code["300033"].group == "计算机软件-金融IT"
    assert stocks_by_code["300058"].group == "传媒-营销广告"
    assert stocks_by_code["603533"].group == "传媒-IP/语料/版权"
    assert stocks_by_code["300133"].group == "传媒-影视内容"
    assert stocks_by_code["300418"].group == "游戏-AI游戏/互动娱乐"
    assert stocks_by_code["002517"].group == "游戏-AI游戏/互动娱乐"
    assert stocks_by_code["688787"].group == "数据安全-数据服务/AI数据"
    assert stocks_by_code["300271"].group == "计算机软件-政务/医疗IT"
    assert "09999" not in stocks_by_code
    assert {"国产算力-基础软件", "计算机软件-办公/企业智能体"} <= set(
        stocks_by_code["688111"].groups
    )
    assert {"计算机软件-搜索/知识管理", "计算机软件-教育信息化/AI教育"} <= set(
        stocks_by_code["002230"].groups
    )
    assert {"国产算力-基础软件", "计算机软件-金融IT"} <= set(
        stocks_by_code["301236"].groups
    )
    assert {"国产算力-数据库/中间件", "计算机软件-政务/医疗IT"} <= set(
        stocks_by_code["002368"].groups
    )
    assert stocks_by_code["600030"].group == "大金融-证券"
    assert stocks_by_code["601398"].group == "大金融-银行"
    assert stocks_by_code["601318"].group == "大金融-保险"
    assert stocks_by_code["600519"].group == "消费-白酒/食品饮料"
    assert stocks_by_code["000333"].group == "消费-家电"
    assert stocks_by_code["601888"].group == "消费-零售/免税"
    assert stocks_by_code["300144"].group == "消费-旅游酒店"
    assert stocks_by_code["600048"].group == "地产链-开发/物业"
    assert stocks_by_code["002271"].group == "地产链-家居/建材"
    assert stocks_by_code["601088"].group == "红利资产-煤炭"
    assert stocks_by_code["600900"].group == "红利资产-电力/公用事业"
    assert stocks_by_code["601919"].group == "交通运输-航运/港口"
    assert stocks_by_code["601021"].group == "交通运输-航空机场/快递"
    assert stocks_by_code["002714"].group == "农业-养殖/饲料"
    assert stocks_by_code["000998"].group == "农业-种业/粮食"
    assert stocks_by_code["600585"].group == "建筑建材-水泥/玻璃"
    assert stocks_by_code["601668"].group == "建筑建材-基建央企"
    assert stocks_by_code["600938"].group == "石油石化-油气开采/油服"
    assert stocks_by_code["600028"].group == "石油石化-炼化/化纤"
    assert stocks_by_code["600276"].group == "医药-创新药"
    assert stocks_by_code["600436"].group == "医药-中药"
    assert stocks_by_code["600161"].group == "医药-血制品"
    assert {"医药-血制品", "医药-疫苗"} <= set(stocks_by_code["002007"].groups)
    assert stocks_by_code["000739"].group == "医药-原料药"
    assert stocks_by_code["603259"].group == "医药-CXO"
    assert stocks_by_code["300760"].group == "医药-医疗器械"
    assert stocks_by_code["300244"].group == "医药-IVD"
    assert stocks_by_code["300015"].group == "医药-医疗服务"
    assert stocks_by_code["603939"].group == "医药-药店/医药商业"
    assert stocks_by_code["300896"].group == "医药-医美"
    assert stocks_by_code["688133"].group == "医药-生命科学上游"


def test_duplicate_stock_keeps_highest_priority_tier():
    pool = load_stock_pool()
    xingfa = next(stock for stock in pool if stock.code == "600141")

    assert xingfa.tier == 1


def test_stock_pool_has_no_default_stars():
    assert "star: true" not in CONFIG_PATH.read_text(encoding="utf-8")


def test_frontend_groups_software_media_game_and_data_security_families():
    app_js = (CONFIG_PATH.parents[1] / "static" / "app.js").read_text(encoding="utf-8")

    expected_families = [
        "电子元件",
        "化工",
        "新能源",
        "半导体芯片",
        "先进封装",
        "半导体材料",
        "半导体设备",
        "机器人",
        "算力基础设施",
        "计算机软件",
        "传媒",
        "游戏",
        "数据安全",
        "大金融",
        "消费",
        "地产链",
        "红利资产",
        "交通运输",
        "农业",
        "建筑建材",
        "石油石化",
    ]
    for family in expected_families:
        assert f'label: "{family}"' in app_js
        assert f'prefixes: ["{family}-"]' in app_js

    assert "FAMILY_ORDER_STORAGE_KEY" in app_js
    assert "getOrderedGroupFamilies" in app_js
    assert "bindFamilyDragHandlers" in app_js
    assert 'draggable="true"' in app_js
    assert "function groupPctClass" in app_js
    assert 'return "strong-pos"' in app_js
    assert 'return "strong-neg"' in app_js
    assert "stock-group-link" in app_js
    assert "selectSector(groupBtn.dataset.group)" in app_js


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
    assert not store.is_group_starred("机器人-本体/核心零部件")
    assert store.toggle_group("机器人-本体/核心零部件") is True
    assert store.is_group_starred("机器人-本体/核心零部件")
    assert store.group_count == 1

    reloaded = StarStore(path)
    assert reloaded.is_group_starred("机器人-本体/核心零部件")
    assert reloaded.toggle_group("机器人-本体/核心零部件") is False
    assert not reloaded.is_group_starred("机器人-本体/核心零部件")


def test_star_store_supports_holdings(tmp_path):
    path = tmp_path / "star_state.json"
    path.write_text('{"stars": [], "groups": []}', encoding="utf-8")
    store = StarStore(path)

    assert store.holding_count == 0
    assert not store.is_holding("600000")
    assert store.toggle_holding("600000") is True
    assert store.is_holding("600000")
    assert store.holding_count == 1

    reloaded = StarStore(path)
    assert reloaded.is_holding("600000")
    assert reloaded.toggle_holding("600000") is False
    assert not reloaded.is_holding("600000")


def test_service_toggle_holding_updates_stock(monkeypatch):
    from app import service as service_module
    from app.service import RadarService

    class FakeStarStore:
        def toggle_holding(self, code):
            return code == "600000"

    monkeypatch.setattr(service_module, "star_store", FakeStarStore())
    service = RadarService.__new__(RadarService)
    service.stocks = [{"code": "600000", "holding": False}]

    assert service.toggle_holding("600000") is True
    assert service.stocks[0]["holding"] is True


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
    assert "group_stats" in data
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
            return group == "机器人-本体/核心零部件"

    monkeypatch.setattr(service_module, "star_store", FakeStarStore())

    service = RadarService.__new__(RadarService)
    service._refresh_state_lock = threading.RLock()
    service._refreshing = False
    service._pending_force_history = False
    service.pool = [object()]
    service.stocks = [
        {
            "code": "688017",
            "group": "机器人-本体/核心零部件",
            "groups": ["机器人-本体/核心零部件"],
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
    assert dashboard["group_stats"]["机器人-本体/核心零部件"]["star"] is True


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


def test_market_index_refresh_keeps_cached_missing_items_and_intraday(monkeypatch):
    from app.service import RadarService
    import app.service as service_module

    service = RadarService.__new__(RadarService)
    service.errors = []
    service.market_indices = [
        {
            "code": "N225",
            "name": "日经225",
            "price": 71854.88,
            "intraday": [70000.0, 70100.0],
        },
        {
            "code": "KS11",
            "name": "韩国KOSPI",
            "price": 8908.8,
            "intraday": [8700.0, 8800.0],
        },
    ]
    monkeypatch.setattr(
        service_module,
        "fetch_market_indices",
        lambda: [
            {
                "code": "N225",
                "name": "日经225",
                "price": 71900.0,
                "intraday": [],
            }
        ],
    )

    service._refresh_market_indices()
    by_code = {index["code"]: index for index in service.market_indices}

    assert by_code["N225"]["price"] == 71900.0
    assert by_code["N225"]["intraday"] == [70000.0, 70100.0]
    assert by_code["N225"]["intraday_cached"] is True
    assert by_code["KS11"]["price"] == 8908.8
    assert by_code["KS11"]["stale"] is True


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
