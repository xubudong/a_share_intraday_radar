from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_klines (
    code TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    close REAL,
    high REAL,
    low REAL,
    volume REAL,
    amount REAL,
    amplitude REAL,
    pct_chg REAL,
    change REAL,
    turnover REAL,
    source TEXT,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_daily_klines_code_date
ON daily_klines(code, date DESC);
"""


class DailyKlineStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.init_schema()

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def init_schema(self) -> None:
        with self._lock, self.connect() as conn:
            conn.executescript(SCHEMA)

    def replace_rows(self, code: str, rows: list[dict[str, Any]]) -> None:
        with self._lock, self.connect() as conn:
            conn.execute("DELETE FROM daily_klines WHERE code = ?", (code,))
            conn.executemany(
                """
                INSERT OR REPLACE INTO daily_klines (
                    code, date, open, close, high, low, volume, amount,
                    amplitude, pct_chg, change, turnover, source
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [row_values(code, row) for row in rows if row.get("date")],
            )

    def get_rows(self, code: str, limit: int | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [code]
        sql = """
            SELECT date, open, close, high, low, volume, amount,
                   amplitude, pct_chg, change, turnover, source
            FROM daily_klines
            WHERE code = ?
            ORDER BY date DESC
        """
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock, self.connect() as conn:
            rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
        rows.reverse()
        return rows

    def has_rows(self, code: str) -> bool:
        with self._lock, self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM daily_klines WHERE code = ? LIMIT 1",
                (code,),
            ).fetchone()
        return row is not None

    def count_codes(self) -> int:
        with self._lock, self.connect() as conn:
            row = conn.execute("SELECT COUNT(DISTINCT code) AS count FROM daily_klines").fetchone()
        return int(row["count"] or 0)

    def prune_codes(self, valid_codes: set[str]) -> None:
        if not valid_codes:
            return
        with self._lock, self.connect() as conn:
            codes = {
                str(row["code"])
                for row in conn.execute("SELECT DISTINCT code FROM daily_klines").fetchall()
            }
            stale_codes = sorted(codes - valid_codes)
            if stale_codes:
                conn.executemany(
                    "DELETE FROM daily_klines WHERE code = ?",
                    [(code,) for code in stale_codes],
                )

    def migrate_from_cache(self, klines: dict[str, list[dict[str, Any]]]) -> int:
        migrated = 0
        for code, rows in klines.items():
            if not rows or self.has_rows(code):
                continue
            self.replace_rows(code, rows)
            migrated += 1
        return migrated


def row_values(code: str, row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        code,
        str(row.get("date")),
        number_or_none(row.get("open")),
        number_or_none(row.get("close")),
        number_or_none(row.get("high")),
        number_or_none(row.get("low")),
        number_or_none(row.get("volume")),
        number_or_none(row.get("amount")),
        number_or_none(row.get("amplitude")),
        number_or_none(row.get("pct_chg")),
        number_or_none(row.get("change")),
        number_or_none(row.get("turnover")),
        row.get("source"),
    )


def number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
