from datetime import date, datetime
import threading
import time

from fastapi.testclient import TestClient
import pytest

from app.config import StockConfig
import app.server as server_module
from app.service import radar_service
import app.sentiment as sentiment_module
from app.sentiment import (
    SentimentMarkStore,
    SentimentService,
    SourceResult,
    build_payload,
    derive_display_payload,
    item_stable_id,
    match_stock_pool,
    run_source,
    write_payload,
)


def sample_pool():
    return [
        StockConfig(
            code="300476",
            name="胜宏科技",
            group="PCB",
            groups=("PCB",),
            note="AI服务器/HPC高阶PCB核心",
            tier=1,
        ),
        StockConfig(
            code="300308",
            name="中际旭创",
            group="光模块-整机",
            groups=("光模块-整机",),
            note="龙头锚",
            tier=1,
        ),
    ]


def sample_payload():
    return build_payload(
        date(2026, 6, 30),
        [
            SourceResult(
                name="wallstreetcn_a_stock",
                status="ok",
                elapsed_sec=0.1,
                items=[
                    {
                        "title": "PCB板块走强，胜宏科技放量拉升",
                        "content": "AI服务器需求继续验证，高阶PCB链条受关注。",
                        "published_at": "2026-06-30T10:15:00+08:00",
                        "source": "wallstreetcn_lives",
                        "channel": "a-stock-channel",
                        "raw": {"score": 3},
                    }
                ],
            ),
            SourceResult(
                name="wallstreetcn_global",
                status="ok",
                elapsed_sec=0.1,
                items=[
                    {
                        "title": "海外算力链继续活跃",
                        "content": "光模块-整机方向反复被资金关注。",
                        "published_at": "2026-06-30T09:20:00+08:00",
                        "source": "wallstreetcn_lives",
                        "channel": "global-channel",
                    }
                ],
            ),
            SourceResult(
                name="levistock_market_emotion",
                status="ok",
                elapsed_sec=0.1,
                items=[{"market_degree": "72", "up_ratio": "58%", "profit_ratio": "强"}],
            ),
            SourceResult(
                name="levistock_market_wind",
                status="ok",
                elapsed_sec=0.1,
                items=[{"plate_name": "PCB", "catalyst": "AI服务器订单推动"}],
            ),
            SourceResult(
                name="zzshare_review_uplimit",
                status="ok",
                elapsed_sec=0.1,
                items=[
                    {
                        "stock_code": "300476",
                        "stock_name": "胜宏科技",
                        "reason": "PCB主线延续",
                    }
                ],
            ),
        ],
        generated_at=datetime(2026, 6, 30, 10, 30),
        total_elapsed_sec=0.5,
    )


def test_raw_payload_derives_timeline_and_market_sections():
    payload = sample_payload()
    data = derive_display_payload(payload, pool=sample_pool())

    assert data["status"] == "ok"
    assert [item["source"] for item in data["timeline"]] == [
        "wallstreetcn_a_stock",
        "wallstreetcn_global",
    ]
    first = data["timeline"][0]
    assert first["auto_matched"] is True
    assert first["matched_stocks"][0]["code"] == "300476"
    assert "PCB" in first["matched_groups"]
    assert first["importance_score"] == 3
    assert first["importance_label"] == "重要"
    assert len(data["market_sections"]) == 7
    assert any(section["name"] == "levistock_market_emotion" for section in data["market_sections"])
    assert any(section["name"] == "zzshare_review_uplimit" for section in data["market_sections"])


def test_timeline_deduplicates_same_day_news_across_channels():
    payload = build_payload(
        date(2026, 6, 30),
        [
            SourceResult(
                name="wallstreetcn_global",
                status="ok",
                elapsed_sec=0.1,
                items=[
                    {
                        "title": "同一条新闻",
                        "content": "完全相同正文。",
                        "published_at": "2026-06-30T09:30:00+08:00",
                    }
                ],
            ),
            SourceResult(
                name="wallstreetcn_a_stock",
                status="ok",
                elapsed_sec=0.1,
                items=[
                    {
                        "title": "同一条新闻",
                        "content": "完全相同正文。",
                        "published_at": "2026-06-30T09:31:00+08:00",
                    }
                ],
            ),
        ],
    )

    data = derive_display_payload(payload, pool=sample_pool())

    assert len(data["timeline"]) == 1
    assert data["timeline"][0]["source"] == "wallstreetcn_a_stock"
    assert data["timeline"][0]["duplicate_count"] == 2


def test_timeline_score_two_is_labeled_as_key_news():
    payload = build_payload(
        date(2026, 6, 30),
        [
            SourceResult(
                name="wallstreetcn_global",
                status="ok",
                elapsed_sec=0.1,
                items=[
                    {
                        "title": "重点新闻",
                        "content": "score 为 2 的消息",
                        "published_at": "2026-06-30T09:30:00+08:00",
                        "raw": {"score": 2},
                    }
                ],
            )
        ],
    )

    data = derive_display_payload(payload, pool=sample_pool())

    assert data["timeline"][0]["importance_score"] == 2
    assert data["timeline"][0]["importance_label"] == "重点"


def test_stock_pool_matching_hits_code_name_group_and_note():
    match_index = sentiment_module.build_match_index(sample_pool())

    by_code = match_stock_pool("300476 今日异动", match_index)
    by_name = match_stock_pool("胜宏科技受益", match_index)
    by_group = match_stock_pool("PCB板块走强", match_index)
    by_note = match_stock_pool("高阶PCB核心公司受关注", match_index)

    assert by_code["matched_stocks"][0]["code"] == "300476"
    assert by_name["matched_stocks"][0]["name"] == "胜宏科技"
    assert "PCB" in by_group["matched_groups"]
    assert by_note["matched_stocks"][0]["code"] == "300476"


def test_item_id_is_stable_and_mark_store_persists(tmp_path):
    item_id = item_stable_id("wallstreetcn_a_stock", "2026-06-30T10:15:00+08:00", "标题", "内容")
    assert item_id == item_stable_id("wallstreetcn_a_stock", "2026-06-30T10:15:00+08:00", "标题", "内容")

    store = SentimentMarkStore(tmp_path / "sentiment_marks.json")
    assert store.toggle(item_id) is True
    assert item_id in store.marked_ids()
    reloaded = SentimentMarkStore(tmp_path / "sentiment_marks.json")
    assert reloaded.is_marked(item_id)
    assert reloaded.toggle(item_id) is False


def test_source_failure_stays_in_summary():
    result = run_source("broken_source", lambda: (_ for _ in ()).throw(RuntimeError("boom")), retries=0)
    payload = build_payload(date(2026, 6, 30), [result])

    assert payload["source_summary"][0]["status"] == "error"
    assert payload["source_summary"][0]["item_count"] == 0
    assert "RuntimeError" in payload["source_summary"][0]["error"]


def test_market_page_and_sentiment_api_read_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sentiment_module, "SENTIMENT_DIR", tmp_path / "sentiment")
    write_payload(sample_payload())
    service = SentimentService()
    service.mark_store = SentimentMarkStore(tmp_path / "sentiment_marks.json")
    monkeypatch.setattr(server_module, "sentiment_service", service)
    monkeypatch.setattr(sentiment_module, "load_stock_pool", sample_pool)

    original_start_refresh = radar_service.start_refresh
    radar_service.start_refresh = lambda force_history=False: {
        "accepted": False,
        "refreshing": False,
    }
    try:
        with TestClient(server_module.app) as client:
            page = client.get("/market")
            response = client.get("/api/sentiment", params={"date": "2026-06-30"})
    finally:
        radar_service.start_refresh = original_start_refresh

    assert page.status_code == 200
    assert "市场新闻舆情" in page.text
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["timeline"]
    assert data["market_sections"]
    assert data["source_summary"]


def test_sentiment_mark_api_toggles(tmp_path, monkeypatch):
    service = SentimentService()
    service.mark_store = SentimentMarkStore(tmp_path / "sentiment_marks.json")
    monkeypatch.setattr(server_module, "sentiment_service", service)
    item_id = "a" * 20

    original_start_refresh = radar_service.start_refresh
    radar_service.start_refresh = lambda force_history=False: {
        "accepted": False,
        "refreshing": False,
    }
    try:
        with TestClient(server_module.app) as client:
            first = client.post(f"/api/sentiment/marks/{item_id}/toggle")
            second = client.post(f"/api/sentiment/marks/{item_id}/toggle")
    finally:
        radar_service.start_refresh = original_start_refresh

    assert first.status_code == 200
    assert first.json()["manual_marked"] is True
    assert second.json()["manual_marked"] is False


def test_sentiment_refresh_api_uses_background_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(sentiment_module, "SENTIMENT_DIR", tmp_path / "sentiment")

    entered = threading.Event()

    def fake_collect(target_date, **kwargs):
        entered.set()
        return [SourceResult("wallstreetcn_a_stock", "ok", 0.01, [])]

    monkeypatch.setattr(sentiment_module, "collect_daily_sentiment", fake_collect)
    service = SentimentService()
    service.mark_store = SentimentMarkStore(tmp_path / "sentiment_marks.json")
    monkeypatch.setattr(server_module, "sentiment_service", service)

    original_start_refresh = radar_service.start_refresh
    radar_service.start_refresh = lambda force_history=False: {
        "accepted": False,
        "refreshing": False,
    }
    try:
        with TestClient(server_module.app) as client:
            response = client.post("/api/sentiment/refresh", params={"date": "2026-06-30"})
            assert response.status_code == 200
            assert response.json()["accepted"] is True
            assert entered.wait(timeout=2)
            for _ in range(20):
                if not service.refresh_status()["refreshing"]:
                    break
                time.sleep(0.05)
    finally:
        radar_service.start_refresh = original_start_refresh

    assert (tmp_path / "sentiment" / "2026-06-30" / "payload.json").exists()
