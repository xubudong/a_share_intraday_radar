from fastapi.testclient import TestClient
import pytest

import app.server as server_module
from app.notes import SectorNoteStore, stock_note_scope
from app.service import radar_service


def test_sector_note_store_upserts_lists_and_deletes(tmp_path):
    store = SectorNoteStore(tmp_path / "sector_notes.json")

    first = store.upsert_note("有色", "2026-06-13", "观察稀土强度")
    store.upsert_note("有色", "2026-06-14", "关注铜、钨扩散")
    updated = store.upsert_note("有色", "2026-06-13", "稀土转强，继续跟踪")
    store.upsert_note("化工", "2026-06-14", "磷化工领涨")

    notes = store.list_notes("有色")

    assert [note["date"] for note in notes] == ["2026-06-14", "2026-06-13"]
    assert len(notes) == 2
    assert updated["created_at"] == first["created_at"]
    assert notes[1]["content"] == "稀土转强，继续跟踪"
    assert store.delete_note("有色", "2026-06-13") is True
    assert store.delete_note("有色", "2026-06-13") is False
    assert [note["date"] for note in store.list_notes("有色")] == ["2026-06-14"]


def test_sector_note_store_validates_input(tmp_path):
    store = SectorNoteStore(tmp_path / "sector_notes.json")

    for scope, note_date, content in [
        ("", "2026-06-14", "内容"),
        ("有色", "2026-02-30", "内容"),
        ("有色", "20260614", "内容"),
        ("有色", "2026-06-14", "   "),
    ]:
        try:
            store.upsert_note(scope, note_date, content)
        except ValueError:
            pass
        else:
            raise AssertionError("无效笔记输入应被拒绝")

    assert stock_note_scope("000636") == "stock:000636"
    with pytest.raises(ValueError):
        stock_note_scope("636")


def test_sector_note_store_does_not_overwrite_corrupted_file(tmp_path):
    path = tmp_path / "sector_notes.json"
    path.write_text("{broken", encoding="utf-8")
    store = SectorNoteStore(path)

    with pytest.raises(RuntimeError):
        store.upsert_note("有色", "2026-06-14", "不应覆盖原文件")

    assert path.read_text(encoding="utf-8") == "{broken"


def test_sector_note_api_crud(tmp_path, monkeypatch):
    store = SectorNoteStore(tmp_path / "sector_notes.json")
    monkeypatch.setattr(server_module, "sector_note_store", store)
    original_start_refresh = radar_service.start_refresh
    radar_service.start_refresh = lambda force_history=False: {
        "accepted": False,
        "refreshing": False,
    }
    try:
        with TestClient(server_module.app) as client:
            created = client.put(
                "/api/sector-notes/2026-06-14",
                json={"scope": "有色", "content": "关注稀土与铜"},
            )
            listed = client.get("/api/sector-notes", params={"scope": "有色"})
            updated = client.put(
                "/api/sector-notes/2026-06-14",
                json={"scope": "有色", "content": "关注稀土、铜和钨"},
            )
            deleted = client.delete(
                "/api/sector-notes/2026-06-14",
                params={"scope": "有色"},
            )
            missing = client.delete(
                "/api/sector-notes/2026-06-14",
                params={"scope": "有色"},
            )
    finally:
        radar_service.start_refresh = original_start_refresh

    assert created.status_code == 200
    assert listed.status_code == 200
    assert listed.json()[0]["content"] == "关注稀土与铜"
    assert updated.json()["content"] == "关注稀土、铜和钨"
    assert deleted.json()["deleted"] is True
    assert missing.status_code == 404


def test_stock_note_api_crud(tmp_path, monkeypatch):
    store = SectorNoteStore(tmp_path / "sector_notes.json")
    monkeypatch.setattr(server_module, "sector_note_store", store)
    original_start_refresh = radar_service.start_refresh
    radar_service.start_refresh = lambda force_history=False: {
        "accepted": False,
        "refreshing": False,
    }
    try:
        with TestClient(server_module.app) as client:
            created = client.put(
                "/api/stock-notes/000636/2026-06-15",
                json={"content": "等待放量突破"},
            )
            listed = client.get("/api/stock-notes", params={"code": "000636"})
            updated = client.put(
                "/api/stock-notes/000636/2026-06-15",
                json={"content": "缩量整理，继续观察"},
            )
            deleted = client.delete("/api/stock-notes/000636/2026-06-15")
            invalid = client.get("/api/stock-notes", params={"code": "636"})
    finally:
        radar_service.start_refresh = original_start_refresh

    assert created.status_code == 200
    assert listed.json()[0]["content"] == "等待放量突破"
    assert updated.json()["content"] == "缩量整理，继续观察"
    assert deleted.json()["deleted"] is True
    assert invalid.status_code == 400
