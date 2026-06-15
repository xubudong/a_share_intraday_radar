from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import ROOT_DIR, StockConfig, load_stock_pool, star_store
from .eastmoney import fetch_daily_klines, fetch_intraday_trends, fetch_realtime_quotes
from .indicators import compute_indicators
from .signals import evaluate_signal


try:
    SH_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # Windows embeddable runtimes may not include IANA tzdata.
    SH_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")
CACHE_PATH = ROOT_DIR / "data" / "state_cache.json"
SNAPSHOTS_DIR = ROOT_DIR / "data" / "snapshots"
HISTORY_REFRESH_SECONDS = 30 * 60
FETCH_WORKERS = 6
INTRADAY_REFRESH_SECONDS = 5 * 60
INTRADAY_RETRY_SECONDS = 45
INTRADAY_MAX_PER_REFRESH = 24
INTRADAY_WORKERS = 3


SPARKLINE_POINTS = 80  # Number of sampled points for sparkline


class RadarService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._refresh_state_lock = threading.RLock()
        self._refreshing = False
        self._pending_force_history = False
        self._refresh_thread: threading.Thread | None = None
        self.pool = load_stock_pool()
        self.quotes: dict[str, dict[str, Any]] = {}
        self.klines: dict[str, list[dict[str, Any]]] = {}
        self.intraday: dict[str, list[float]] = {}
        self.intraday_loaded_at: dict[str, float] = {}
        self.intraday_attempted_at: dict[str, float] = {}
        self.history_loaded_at: dict[str, float] = {}
        self.stocks: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.last_refresh_at: str | None = None
        self.last_success_at: str | None = None
        self.last_refresh_mode = "none"
        self.load_cache()

    def start_refresh(self, force_history: bool = False) -> dict[str, Any]:
        """Start one background refresh and coalesce duplicate requests."""
        with self._refresh_state_lock:
            if self._refreshing:
                if force_history:
                    self._pending_force_history = True
                return self.refresh_status(accepted=False)

            self._refreshing = True
            thread = threading.Thread(
                target=self._run_refresh_queue,
                args=(force_history,),
                daemon=True,
            )
            self._refresh_thread = thread
            thread.start()
            return self.refresh_status(accepted=True)

    def _run_refresh_queue(self, force_history: bool) -> None:
        current_force_history = force_history
        while True:
            try:
                self.refresh(force_history=current_force_history)
            except Exception as exc:  # pragma: no cover - last-resort worker protection
                self.errors.append(
                    {"scope": "refresh", "message": str(exc), "time": now_iso()}
                )

            with self._refresh_state_lock:
                if self._pending_force_history:
                    self._pending_force_history = False
                    current_force_history = True
                    continue
                self._refreshing = False
                self._refresh_thread = None
                return

    def refresh_status(self, accepted: bool | None = None) -> dict[str, Any]:
        with self._refresh_state_lock:
            status = {
                "refreshing": self._refreshing,
                "pending_force_history": self._pending_force_history,
                "mode": self.last_refresh_mode,
            }
            if accepted is not None:
                status["accepted"] = accepted
            return status

    def load_cache(self) -> None:
        if not CACHE_PATH.exists():
            return
        try:
            data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            self.quotes = data.get("quotes", {})
            self.klines = data.get("klines", {})
            self.intraday = data.get("intraday", {})
            self.intraday_loaded_at = data.get("intraday_loaded_at", {})
            self.intraday_attempted_at = data.get("intraday_attempted_at", {})
            self.history_loaded_at = data.get("history_loaded_at", {})
            self.last_success_at = data.get("last_success_at")
            self.stocks = self.build_stocks()
        except Exception as exc:  # pragma: no cover - cache corruption should not block app
            self.errors.append({"scope": "cache", "message": str(exc), "time": now_iso()})

    def save_cache(self) -> None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "quotes": self.quotes,
            "klines": self.klines,
            "intraday": self.intraday,
            "intraday_loaded_at": self.intraday_loaded_at,
            "intraday_attempted_at": self.intraday_attempted_at,
            "history_loaded_at": self.history_loaded_at,
            "last_success_at": self.last_success_at,
        }
        CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def refresh(self, force_history: bool = False) -> dict[str, Any]:
        with self._lock:
            started = now_iso()
            self.last_refresh_at = started
            self.last_refresh_mode = "manual" if force_history else "auto"
            self.errors = []
            self.pool = load_stock_pool()
            codes = [stock.code for stock in self.pool]
            valid_codes = set(codes)
            self.quotes = {code: value for code, value in self.quotes.items() if code in valid_codes}
            self.klines = {code: value for code, value in self.klines.items() if code in valid_codes}
            self.intraday = {code: value for code, value in self.intraday.items() if code in valid_codes}
            self.intraday_loaded_at = {
                code: value
                for code, value in self.intraday_loaded_at.items()
                if code in valid_codes
            }
            self.intraday_attempted_at = {
                code: value
                for code, value in self.intraday_attempted_at.items()
                if code in valid_codes
            }

            try:
                refreshed_quotes = fetch_realtime_quotes(codes)
                self.quotes.update(refreshed_quotes)
                missing_codes = [code for code in codes if code not in refreshed_quotes]
                if missing_codes:
                    self.errors.append(
                        {
                            "scope": "realtime",
                            "message": f"实时行情缺失 {len(missing_codes)} 只",
                            "codes": missing_codes,
                            "time": now_iso(),
                        }
                    )
            except Exception as exc:
                self.errors.append({"scope": "realtime", "message": str(exc), "time": now_iso()})

            stale_stocks = [
                stock
                for stock in self.pool
                if force_history or self.history_is_stale(stock.code)
            ]
            with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
                futures = {
                    executor.submit(fetch_daily_klines, stock.code): stock
                    for stock in stale_stocks
                }
                for future in as_completed(futures):
                    stock = futures[future]
                    try:
                        rows = future.result()
                        if rows:
                            self.klines[stock.code] = rows
                            self.history_loaded_at[stock.code] = time.time()
                    except Exception as exc:
                        self.errors.append(
                            {
                                "scope": "history",
                                "code": stock.code,
                                "name": stock.name,
                                "message": str(exc),
                                "time": now_iso(),
                            }
                        )

            self._refresh_intraday()
            self.stocks = self.build_stocks()

            if self.stocks:
                self.last_success_at = now_iso()
                self.save_cache()
                if force_history:
                    self.save_snapshot()
            return self.dashboard()

    def history_is_stale(self, code: str) -> bool:
        if code not in self.klines:
            return True
        loaded_at = float(self.history_loaded_at.get(code) or 0)
        return time.time() - loaded_at > HISTORY_REFRESH_SECONDS

    def build_stocks(self) -> list[dict[str, Any]]:
        items = []
        for stock in self.pool:
            quote = self.quotes.get(stock.code, {})
            rows = merge_intraday_quote(self.klines.get(stock.code, []), quote)
            indicators = compute_indicators(rows)
            price = quote.get("price") or (rows[-1]["close"] if rows else None)
            starred = star_store.is_starred(stock.code)
            item = {
                "code": stock.code,
                "name": stock.name,
                "group": stock.group,
                "groups": list(stock.groups),
                "star": starred,
                "watch": stock.watch,
                "note": stock.note,
                "tier": stock.tier,
                "price": price,
                "quote": quote,
                "indicators": indicators,
                "data_status": data_status(quote, rows),
            }
            item["signal"] = evaluate_signal(item)
            item["intraday"] = self.intraday.get(stock.code, [])
            items.append(item)
        return sorted(
            items,
            key=lambda row: (
                -row["signal"]["rank_score"],
                not row.get("star"),
                row.get("group", ""),
                row.get("code", ""),
            ),
        )

    def dashboard(self) -> dict[str, Any]:
        signal_counts = Counter(stock["signal"]["signal"] for stock in self.stocks)
        group_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"total": 0, "signals": Counter()})
        for stock in self.stocks:
            for group in stock.get("groups") or [stock["group"]]:
                group_stats[group]["total"] += 1
                group_stats[group]["signals"][stock["signal"]["signal"]] += 1

        radar = [
            stock
            for stock in self.stocks
            if stock["signal"]["signal"] in {"可试仓", "二次确认", "突破观察"}
        ][:12]

        # ── 涨跌统计 ──
        up, down, flat, pcts = 0, 0, 0, []
        pcts_main: list[float] = []   # 主板
        pcts_gem: list[float] = []    # 创业板/科创板
        group_pcts: dict[str, list[float]] = defaultdict(list)
        tier_pcts: dict[int, list[float]] = defaultdict(list)
        for stock in self.stocks:
            pct = (stock.get("quote") or {}).get("pct_chg")
            groups = stock.get("groups") or [stock.get("group", "")]
            if pct is None:
                flat += 1
            elif pct > 0:
                up += 1
                pcts.append(pct)
            elif pct < 0:
                down += 1
                pcts.append(pct)
            else:
                flat += 1
                pcts.append(pct)
            # Board classification
            if pct is not None:
                code = stock.get("code", "")
                if code.startswith(("688", "300", "301")):
                    pcts_gem.append(pct)
                else:
                    pcts_main.append(pct)
                tier = int(stock.get("tier") or 0)
                if tier in (1, 2, 3):
                    tier_pcts[tier].append(pct)
                for group in groups:
                    if group:
                        group_pcts[group].append(pct)
        avg_pct = sum(pcts) / len(pcts) if pcts else 0
        avg_pct_main = sum(pcts_main) / len(pcts_main) if pcts_main else 0
        avg_pct_gem = sum(pcts_gem) / len(pcts_gem) if pcts_gem else 0

        return {
            "updated_at": self.last_refresh_at,
            "last_success_at": self.last_success_at,
            "refresh": self.refresh_status(),
            "market_session": market_session(),
            "data_source": {
                "realtime": "eastmoney/tencent",
                "history": "eastmoney_kline",
                "status": "partial_error" if self.errors else "ok",
                "errors": self.errors[-12:],
            },
            "summary": {
                "total": len(self.pool),
                "stars": star_store.count,
                "actionable": sum(signal_counts[s] for s in ["可试仓", "二次确认", "突破观察"]),
                "overheated": signal_counts["过热不追"],
                "weak": signal_counts["走弱剔除"],
                "up": up,
                "down": down,
                "flat": flat,
                "avg_pct": round(avg_pct, 2),
                "avg_pct_main": round(avg_pct_main, 2),
                "avg_pct_gem": round(avg_pct_gem, 2),
                "avg_pct_t1": average_or_none(tier_pcts[1]),
                "avg_pct_t2": average_or_none(tier_pcts[2]),
                "avg_pct_t3": average_or_none(tier_pcts[3]),
            },
            "signal_counts": dict(signal_counts),
            "group_stats": {
                name: {
                    "total": value["total"],
                    "signals": dict(value["signals"]),
                    "avg_pct": round(sum(group_pcts.get(name, [])) / len(group_pcts.get(name, [])), 2) if group_pcts.get(name) else None,
                }
                for name, value in group_stats.items()
            },
            "radar": radar,
        }

    def stocks_payload(self) -> dict[str, Any]:
        return {
            "updated_at": self.last_refresh_at,
            "last_success_at": self.last_success_at,
            "stocks": self.stocks,
        }

    def toggle_star(self, code: str) -> bool:
        """Toggle star for a stock code. Returns new starred state."""
        new_state = star_store.toggle(code)
        # Update in-memory stock list
        for stock in self.stocks:
            if stock["code"] == code:
                stock["star"] = new_state
                break
        return new_state

    # ── Intraday Trends ──

    def _refresh_intraday(self) -> None:
        """Refresh a limited batch and retain previously fetched sparklines."""
        now = time.time()
        candidates = []
        for stock in self.pool:
            code = stock.code
            attempted_at = float(self.intraday_attempted_at.get(code) or 0)
            loaded_at = float(self.intraday_loaded_at.get(code) or 0)
            if now - attempted_at < INTRADAY_RETRY_SECONDS:
                continue
            if self.intraday.get(code) and now - loaded_at < INTRADAY_REFRESH_SECONDS:
                continue
            candidates.append(stock)
        candidates.sort(
            key=lambda stock: (
                bool(self.intraday.get(stock.code)),
                float(self.intraday_loaded_at.get(stock.code) or 0),
            )
        )
        candidates = candidates[:INTRADAY_MAX_PER_REFRESH]
        for stock in candidates:
            self.intraday_attempted_at[stock.code] = now

        with ThreadPoolExecutor(max_workers=INTRADAY_WORKERS) as executor:
            futures = {
                executor.submit(fetch_intraday_trends, stock.code): stock.code
                for stock in candidates
            }
            for future in as_completed(futures):
                code = futures[future]
                try:
                    prices = future.result()
                    if prices:
                        self.intraday[code] = sample_sparkline(prices, SPARKLINE_POINTS)
                        self.intraday_loaded_at[code] = time.time()
                except Exception:
                    pass  # Non-fatal: sparkline simply won't render


    # ── Snapshots ──

    def save_snapshot(self) -> str:
        """Save current stocks payload as a snapshot. Returns snapshot ID (timestamp)."""
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(SH_TZ).strftime("%Y%m%dT%H%M%S")
        payload = {
            "id": ts,
            "created_at": now_iso(),
            "summary": self.dashboard().get("summary", {}),
            "stocks": self.stocks,
        }
        path = SNAPSHOTS_DIR / f"{ts}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return ts

    def list_snapshots(self) -> list[dict[str, Any]]:
        """Return metadata for all snapshots, newest first."""
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        results = []
        for path in sorted(SNAPSHOTS_DIR.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append({
                    "id": data["id"],
                    "created_at": data["created_at"],
                    "summary": data.get("summary", {}),
                    "stock_count": len(data.get("stocks", [])),
                })
            except Exception:
                pass
        return results[:60]  # Keep at most 60 snapshots in listing

    def load_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        """Load a snapshot by ID. Returns None if not found."""
        path = snapshot_path(snapshot_id)
        if path is None:
            return None
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot by ID. Returns False when it does not exist."""
        path = snapshot_path(snapshot_id)
        if path is None or not path.is_file():
            return False
        path.unlink()
        return True

    def health(self) -> dict[str, Any]:
        has_quotes = len(self.quotes) >= len(self.pool)
        has_indicators = sum(1 for stock in self.stocks if stock.get("indicators", {}).get("rsi14") is not None)
        has_intraday = sum(1 for stock in self.stocks if len(stock.get("intraday") or []) >= 2)
        return {
            "ok": bool(self.stocks) and has_quotes and has_indicators >= max(1, len(self.pool) // 2),
            "refreshing": self._refreshing,
            "pending_force_history": self._pending_force_history,
            "pool_size": len(self.pool),
            "quote_count": len(self.quotes),
            "kline_count": len(self.klines),
            "indicator_count": has_indicators,
            "intraday_count": has_intraday,
            "last_refresh_at": self.last_refresh_at,
            "last_success_at": self.last_success_at,
            "cache_path": str(CACHE_PATH),
            "errors": self.errors[-20:],
        }


def sample_sparkline(prices: list[float], n: int) -> list[float]:
    """Downsample a price series to at most *n* points for sparkline rendering."""
    if len(prices) <= n:
        return prices
    step = len(prices) / n
    return [prices[int(i * step)] for i in range(n)]


def average_or_none(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def snapshot_path(snapshot_id: str) -> Path | None:
    if not re.fullmatch(r"\d{8}T\d{6}", snapshot_id):
        return None
    return SNAPSHOTS_DIR / f"{snapshot_id}.json"


def merge_intraday_quote(rows: list[dict[str, Any]], quote: dict[str, Any]) -> list[dict[str, Any]]:
    if not rows or not quote.get("price"):
        return rows

    today = datetime.now(SH_TZ).strftime("%Y-%m-%d")
    price = float(quote["price"])
    prev_close = quote.get("prev_close") or rows[-1].get("close") or price
    intraday_row = {
        "date": today,
        "open": quote.get("open") or rows[-1].get("open") or price,
        "close": price,
        "high": quote.get("high") or max(price, rows[-1].get("high") or price),
        "low": quote.get("low") or min(price, rows[-1].get("low") or price),
        "volume": quote.get("volume") or rows[-1].get("volume") or 0,
        "amount": quote.get("amount") or rows[-1].get("amount") or 0,
        "pct_chg": ((price / prev_close - 1) * 100) if prev_close else 0,
    }

    merged = list(rows)
    if merged[-1].get("date") == today:
        merged[-1] = {**merged[-1], **intraday_row}
    else:
        merged.append(intraday_row)
    return merged


def data_status(quote: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    if quote and rows:
        return "live"
    if quote:
        return "quote_only"
    if rows:
        return "history_only"
    return "missing"


def market_session() -> dict[str, Any]:
    now = datetime.now(SH_TZ)
    minutes = now.hour * 60 + now.minute
    morning = 9 * 60 + 30 <= minutes <= 11 * 60 + 30
    afternoon = 13 * 60 <= minutes <= 15 * 60
    weekday = now.weekday() < 5
    is_open = weekday and (morning or afternoon)
    return {
        "is_open": is_open,
        "label": "盘中" if is_open else "非盘中",
        "now": now.isoformat(timespec="seconds"),
    }


def now_iso() -> str:
    return datetime.now(SH_TZ).isoformat(timespec="seconds")


radar_service = RadarService()
