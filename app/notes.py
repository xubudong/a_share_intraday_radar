from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import ROOT_DIR


SECTOR_NOTES_PATH = ROOT_DIR / "data" / "sector_notes.json"
NOTE_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
STOCK_CODE_PATTERN = re.compile(r"\d{6}")


class SectorNoteStore:
    """按板块和日期保存研究笔记。"""

    def __init__(self, path: Path = SECTOR_NOTES_PATH) -> None:
        self._path = path
        self._lock = threading.RLock()

    def list_notes(self, scope: str) -> list[dict[str, Any]]:
        scope = validate_scope(scope)
        with self._lock:
            notes = [
                note
                for note in self._read_notes()
                if note.get("scope") == scope
            ]
        return sorted(
            notes,
            key=lambda note: (note.get("date", ""), note.get("updated_at", "")),
            reverse=True,
        )

    def upsert_note(self, scope: str, note_date: str, content: str) -> dict[str, Any]:
        scope = validate_scope(scope)
        note_date = validate_note_date(note_date)
        content = content.strip()
        if not content:
            raise ValueError("笔记内容不能为空")
        if len(content) > 20000:
            raise ValueError("笔记内容不能超过 20000 字")

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._lock:
            notes = self._read_notes()
            current = next(
                (
                    note
                    for note in notes
                    if note.get("scope") == scope and note.get("date") == note_date
                ),
                None,
            )
            if current is None:
                current = {
                    "scope": scope,
                    "date": note_date,
                    "content": content,
                    "created_at": now,
                    "updated_at": now,
                }
                notes.append(current)
            else:
                current["content"] = content
                current["updated_at"] = now
            self._write_notes(notes)
            return dict(current)

    def delete_note(self, scope: str, note_date: str) -> bool:
        scope = validate_scope(scope)
        note_date = validate_note_date(note_date)
        with self._lock:
            notes = self._read_notes()
            remaining = [
                note
                for note in notes
                if not (
                    note.get("scope") == scope
                    and note.get("date") == note_date
                )
            ]
            if len(remaining) == len(notes):
                return False
            self._write_notes(remaining)
            return True

    def _read_notes(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("无法读取板块笔记文件，请先检查文件内容") from exc
        if not isinstance(data, dict) or not isinstance(data.get("notes", []), list):
            raise RuntimeError("板块笔记文件格式无效")
        return data.get("notes", [])

    def _write_notes(self, notes: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps({"version": 1, "notes": notes}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._path)


def validate_scope(scope: str) -> str:
    scope = scope.strip()
    if not scope:
        raise ValueError("板块名称不能为空")
    if len(scope) > 80:
        raise ValueError("板块名称不能超过 80 字")
    return scope


def validate_note_date(note_date: str) -> str:
    if not NOTE_DATE_PATTERN.fullmatch(note_date):
        raise ValueError("日期格式必须为 YYYY-MM-DD")
    try:
        date.fromisoformat(note_date)
    except ValueError as exc:
        raise ValueError("日期无效") from exc
    return note_date


def stock_note_scope(code: str) -> str:
    code = code.strip()
    if not STOCK_CODE_PATTERN.fullmatch(code):
        raise ValueError("股票代码必须为 6 位数字")
    return f"stock:{code}"


sector_note_store = SectorNoteStore()
