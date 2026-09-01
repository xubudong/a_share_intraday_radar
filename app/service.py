from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import ROOT_DIR, StockConfig, load_stock_pool, star_store
from .eastmoney import (
    MARKET_INDICES,
    fetch_daily_klines,
    fetch_intraday_trends,
    fetch_market_indices,
    fetch_realtime_quotes,
)
from .history_store import DailyKlineStore
from .indicators import compute_indicators
from .signals import evaluate_signal
from .taxonomy import build_scope_stats, taxonomy


try:
    SH_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # Windows embeddable runtimes may not include IANA tzdata.
    SH_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


CACHE_PATH = ROOT_DIR / "data" / "state_cache.json"
DB_PATH = ROOT_DIR / "data" / "radar.db"
SNAPSHOTS_DIR = ROOT_DIR / "data" / "snapshots"
FETCH_WORKERS = positive_int_env("HISTORY_FETCH_WORKERS", 2)
HISTORY_BATCH_SIZE = positive_int_env("HISTORY_BATCH_SIZE", 40)
HISTORY_RETRY_SECONDS = positive_int_env("HISTORY_RETRY_SECONDS", 30 * 60)
HISTORY_WINDOW = positive_int_env("HISTORY_WINDOW", 220)
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
        self._history_state_lock = threading.RLock()
        self._history_refreshing = False
        self._history_thread: threading.Thread | None = None
        self._history_total = 0
        self._history_completed = 0
        self._history_updated = 0
        self._history_failed = 0
        self._history_started_at: str | None = None
        self._history_finished_at: str | None = None
        self._history_force_pending = False
        self._history_snapshot_pending = False
        self.pool = load_stock_pool()
        self.quotes: dict[str, dict[str, Any]] = {}
        self.history_store = DailyKlineStore(DB_PATH)
        self.intraday: dict[str, list[float]] = {}
        self.intraday_loaded_at: dict[str, float] = {}
        self.intraday_attempted_at: dict[str, float] = {}
        self.market_indices: list[dict[str, Any]] = []
        self.history_loaded_at: dict[str, float] = {}
        self.history_attempted_at: dict[str, float] = {}
        self.stocks: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.last_refresh_at: str | None = None
        self.last_success_at: str | None = None
        self.last_refresh_mode = "none"
        self.load_cache()

    def start_refresh(self, force_history: bool = False) -> dict[str, Any]:
        """Start one quick quote refresh and coalesce duplicate requests."""
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
            history = self.history_refresh_status()
            status = {
                "refreshing": self._refreshing,
                "pending_force_history": (
                    self._pending_force_history or history.get("pending_force", False)
                ),
                "mode": self.last_refresh_mode,
                "history": history,
            }
            if accepted is not None:
                status["accepted"] = accepted
            return status

    def start_history_refresh(
        self,
        *,
        force_history: bool = False,
        save_snapshot: bool = False,
    ) -> dict[str, Any]:
        """Start one background daily-kline refresh without blocking quote refreshes."""
        lock = getattr(self, "_history_state_lock", None)
        if lock is None:
            return {"refreshing": False, "accepted": False}
        with lock:
            if self._history_refreshing:
                if force_history:
                    self._history_force_pending = True
                    self._history_snapshot_pending = (
                        self._history_snapshot_pending or save_snapshot
                    )
                return self.history_refresh_status(accepted=False)

            candidates = self.stocks_requiring_history(force_history)
            if not candidates:
                self._history_total = 0
                self._history_completed = 0
                self._history_updated = 0
                self._history_failed = 0
                self._history_finished_at = now_iso()
                return self.history_refresh_status(accepted=False)

            self._history_refreshing = True
            self._history_force_pending = False
            self._history_snapshot_pending = save_snapshot
            self._history_total = len(candidates)
            self._history_completed = 0
            self._history_updated = 0
            self._history_failed = 0
            self._history_started_at = now_iso()
            self._history_finished_at = None
            thread = threading.Thread(
                target=self._run_history_refresh_queue,
                args=(candidates, force_history, save_snapshot),
                daemon=True,
            )
            self._history_thread = thread
            thread.start()
            return self.history_refresh_status(accepted=True)

    def _run_history_refresh_queue(
        self,
        candidates: list[StockConfig],
        force_history: bool,
        save_snapshot: bool,
    ) -> None:
        current_candidates = candidates
        current_force_history = force_history
        current_save_snapshot = save_snapshot
        while True:
            try:
                self._refresh_daily_klines(
                    current_candidates,
                    force_history=current_force_history,
                )
                with self._lock:
                    self.stocks = self.build_stocks()
                    if self.stocks:
                        self.last_success_at = now_iso()
                        self.save_cache()
                        if current_save_snapshot:
                            self.save_snapshot()
            except Exception as exc:  # pragma: no cover - last-resort worker protection
                self.errors.append(
                    {"scope": "history", "message": str(exc), "time": now_iso()}
                )

            with self._history_state_lock:
                if self._history_force_pending:
                    self._history_force_pending = False
                    current_force_history = True
                    current_save_snapshot = (
                        current_save_snapshot or self._history_snapshot_pending
                    )
                    self._history_snapshot_pending = False
                    current_candidates = self.stocks_requiring_history(True)
                    self._history_total = len(current_candidates)
                    self._history_completed = 0
                    self._history_updated = 0
                    self._history_failed = 0
                    self._history_started_at = now_iso()
                    self._history_finished_at = None
                    if current_candidates:
                        continue

                self._history_refreshing = False
                self._history_thread = None
                self._history_finished_at = now_iso()
                self._history_snapshot_pending = False
                return

    def history_refresh_status(self, accepted: bool | None = None) -> dict[str, Any]:
        lock = getattr(self, "_history_state_lock", None)
        if lock is None:
            status = {
                "refreshing": False,
                "pending_force": False,
                "total": 0,
                "completed": 0,
                "updated": 0,
                "failed": 0,
                "cached": 0,
                "missing": 0,
                "progress": 0,
            }
        else:
            with lock:
                total = getattr(self, "_history_total", 0)
                completed = getattr(self, "_history_completed", 0)
                cached = self.history_store.count_codes() if hasattr(self, "history_store") else 0
                pool_size = len(getattr(self, "pool", []) or [])
                status = {
                    "refreshing": getattr(self, "_history_refreshing", False),
                    "pending_force": getattr(self, "_history_force_pending", False),
                    "total": total,
                    "completed": completed,
                    "updated": getattr(self, "_history_updated", 0),
                    "failed": getattr(self, "_history_failed", 0),
                    "cached": cached,
                    "missing": max(0, pool_size - cached),
                    "started_at": getattr(self, "_history_started_at", None),
                    "finished_at": getattr(self, "_history_finished_at", None),
                    "progress": round(completed / total * 100, 1) if total else 0,
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
            self.intraday = data.get("intraday", {})
            self.intraday_loaded_at = data.get("intraday_loaded_at", {})
            self.intraday_attempted_at = data.get("intraday_attempted_at", {})
            self.market_indices = data.get("market_indices", [])
            self.history_loaded_at = data.get("history_loaded_at", {})
            self.history_attempted_at = data.get("history_attempted_at", {})
            self.last_success_at = data.get("last_success_at")
            migrated = self.history_store.migrate_from_cache(data.get("klines", {}))
            if migrated:
                service_log(f"已迁移旧日K缓存到 SQLite：{migrated} 只")
                self.save_cache()
            self.stocks = self.build_stocks()
        except Exception as exc:  # pragma: no cover - cache corruption should not block app
            self.errors.append({"scope": "cache", "message": str(exc), "time": now_iso()})

    def save_cache(self) -> None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "quotes": self.quotes,
            "intraday": self.intraday,
            "intraday_loaded_at": self.intraday_loaded_at,
            "intraday_attempted_at": self.intraday_attempted_at,
            "market_indices": self.market_indices,
            "history_loaded_at": self.history_loaded_at,
            "history_attempted_at": self.history_attempted_at,
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
            self.history_store.prune_codes(valid_codes)
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
            self.history_attempted_at = {
                code: value
                for code, value in self.history_attempted_at.items()
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

            self._refresh_market_indices()

            self._refresh_intraday()
            self.stocks = self.build_stocks()
            self.start_history_refresh(
                force_history=force_history,
                save_snapshot=force_history,
            )

            if self.stocks:
                self.last_success_at = now_iso()
                self.save_cache()
            return self.dashboard()

    def stocks_requiring_history(self, force_history: bool) -> list[StockConfig]:
        if force_history:
            return list(self.pool)
        return [
            stock
            for stock in self.pool
            if not self.history_store.has_rows(stock.code) and self.history_retry_is_due(stock.code)
        ]

    def history_retry_is_due(self, code: str) -> bool:
        attempted_at = float(self.history_attempted_at.get(code) or 0)
        return time.time() - attempted_at >= HISTORY_RETRY_SECONDS

    def _refresh_daily_klines(self, stocks: list[StockConfig], *, force_history: bool) -> None:
        if not stocks:
            return

        service_log(
            f"开始刷新日K：{len(stocks)} 只，"
            f"force_history={force_history}，workers={FETCH_WORKERS}，batch={HISTORY_BATCH_SIZE}"
        )
        total = len(stocks)
        for start in range(0, total, HISTORY_BATCH_SIZE):
            batch = stocks[start : start + HISTORY_BATCH_SIZE]
            batch_no = start // HISTORY_BATCH_SIZE + 1
            batch_total = (total + HISTORY_BATCH_SIZE - 1) // HISTORY_BATCH_SIZE
            updated = 0
            service_log(f"刷新日K批次 {batch_no}/{batch_total}：{len(batch)} 只")
            now = time.time()
            for stock in batch:
                self.history_attempted_at[stock.code] = now

            with ThreadPoolExecutor(max_workers=max(1, min(FETCH_WORKERS, len(batch)))) as executor:
                futures = {
                    executor.submit(fetch_daily_klines, stock.code): stock
                    for stock in batch
                }
                for future in as_completed(futures):
                    stock = futures[future]
                    progress_updated = False
                    progress_failed = False
                    try:
                        rows = future.result()
                        if rows:
                            self.history_store.replace_rows(stock.code, rows)
                            self.history_loaded_at[stock.code] = time.time()
                            updated += 1
                            progress_updated = True
                        else:
                            progress_failed = True
                    except Exception as exc:
                        progress_failed = True
                        self.errors.append(
                            {
                                "scope": "history",
                                "code": stock.code,
                                "name": stock.name,
                                "message": str(exc),
                                "time": now_iso(),
                            }
                        )
                    finally:
                        lock = getattr(self, "_history_state_lock", None)
                        if lock is not None:
                            with lock:
                                self._history_completed += 1
                                if progress_updated:
                                    self._history_updated += 1
                                if progress_failed:
                                    self._history_failed += 1

            if updated:
                self.save_cache()
            service_log(f"完成日K批次 {batch_no}/{batch_total}：成功 {updated}/{len(batch)}")

    def build_stocks(self) -> list[dict[str, Any]]:
        items = []
        for stock in self.pool:
            quote = self.quotes.get(stock.code, {})
            rows = merge_intraday_quote(
                self.history_store.get_rows(stock.code, limit=HISTORY_WINDOW),
                quote,
            )
            indicators = compute_indicators(rows)
            price = quote.get("price") or (rows[-1]["close"] if rows else None)
            starred = star_store.is_starred(stock.code)
            holding = star_store.is_holding(stock.code)
            group_starred = any(star_store.is_group_starred(group) for group in stock.groups)
            item = {
                "code": stock.code,
                "name": stock.name,
                "group": stock.group,
                "groups": list(stock.groups),
                "star": starred,
                "holding": holding,
                "group_star": group_starred,
                "watch": stock.watch,
                "note": stock.note,
                "tier": stock.tier,
                "price": price,
                "quote": quote,
                "indicators": indicators,
                "data_status": data_status(quote, rows),
            }
            projection = taxonomy.stock_projection(stock.group, stock.groups)
            item.update(projection)
            item["scope_star"] = any(
                self.is_scope_starred(scope_id)
                for scope_id in [
                    *projection["industry_scope_ids"],
                    *projection["tag_scope_ids"],
                ]
            )
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

        radar = [stock for stock in self.stocks if stock["signal"]["signal"] == "买入"][:12]

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
        scope_stats = build_scope_stats(
            self.stocks,
            taxonomy,
            is_scope_starred=self.is_scope_starred,
        )

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
                "holdings": getattr(star_store, "holding_count", 0),
                "group_stars": self.starred_sector_count(),
                "buy": signal_counts["买入"],
                "reduce": signal_counts["减仓"],
                "exit": signal_counts["剔除"],
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
                    "star": star_store.is_group_starred(name),
                    "avg_pct": round(sum(group_pcts.get(name, [])) / len(group_pcts.get(name, [])), 2) if group_pcts.get(name) else None,
                }
                for name, value in group_stats.items()
            },
            "scope_stats": scope_stats,
            "market_indices": getattr(self, "market_indices", []),
            "radar": radar,
        }

    def stocks_payload(self) -> dict[str, Any]:
        return {
            "updated_at": self.last_refresh_at,
            "last_success_at": self.last_success_at,
            "stocks": self.stocks,
        }

    def taxonomy_payload(self) -> dict[str, Any]:
        return taxonomy.payload(is_scope_starred=self.is_scope_starred)

    def is_scope_starred(self, scope_id: str) -> bool:
        is_scope_starred = getattr(star_store, "is_scope_starred", None)
        if is_scope_starred and is_scope_starred(scope_id):
            return True
        return any(
            star_store.is_group_starred(group)
            for group in taxonomy.legacy_groups_for_scope(scope_id)
        )

    def starred_sector_count(self) -> int:
        starred_groups = getattr(star_store, "starred_groups", None)
        if starred_groups is None:
            return getattr(star_store, "group_count", 0) + getattr(
                star_store, "scope_count", 0
            )
        scopes = set(getattr(star_store, "starred_scopes", ()))
        for group in starred_groups:
            leaf_id = taxonomy.resolve_group(group)
            scopes.add(f"industry:{leaf_id}" if leaf_id else f"legacy:{group}")
        return len(scopes)

    def toggle_star(self, code: str) -> bool:
        """Toggle star for a stock code. Returns new starred state."""
        new_state = star_store.toggle(code)
        # Update in-memory stock list
        for stock in self.stocks:
            if stock["code"] == code:
                stock["star"] = new_state
                break
        return new_state

    def toggle_group_star(self, group: str) -> bool:
        """Toggle star for a sector/group. Returns new starred state."""
        new_state = star_store.toggle_group(group)
        for stock in self.stocks:
            groups = stock.get("groups") or [stock.get("group", "")]
            if group in groups:
                stock["group_star"] = new_state or any(
                    star_store.is_group_starred(item) for item in groups
                )
        return new_state

    def toggle_scope_star(self, scope_id: str) -> bool:
        """Toggle star for a stable taxonomy scope."""
        valid_industry = (
            scope_id.startswith("industry:")
            and scope_id.removeprefix("industry:") in taxonomy.nodes
        )
        valid_tag = (
            scope_id.startswith("tag:")
            and scope_id.removeprefix("tag:") in taxonomy.tags
        )
        if not (valid_industry or valid_tag):
            raise ValueError("未知行业或标签")
        new_state = not self.is_scope_starred(scope_id)
        new_state = star_store.set_scope(
            scope_id,
            new_state,
            remove_legacy_groups=taxonomy.legacy_groups_for_scope(scope_id),
        )
        for stock in self.stocks:
            stock_scopes = [
                *(stock.get("industry_scope_ids") or []),
                *(stock.get("tag_scope_ids") or []),
            ]
            if scope_id in stock_scopes:
                stock["scope_star"] = new_state or any(
                    self.is_scope_starred(item) for item in stock_scopes
                )
        return new_state

    def toggle_holding(self, code: str) -> bool:
        """Toggle holding state for a stock code."""
        new_state = star_store.toggle_holding(code)
        for stock in self.stocks:
            if stock["code"] == code:
                stock["holding"] = new_state
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

    def _refresh_market_indices(self) -> None:
        cached_by_code = {
            str(index.get("code")): index
            for index in getattr(self, "market_indices", [])
            if index.get("code")
        }
        try:
            indices = fetch_market_indices()
        except Exception as exc:
            self.errors.append(
                {"scope": "market_index", "message": str(exc), "time": now_iso()}
            )
            return

        if not indices:
            return
        refreshed_by_code = {
            str(index.get("code")): index
            for index in indices
            if index.get("code")
        }
        merged = []
        for config in MARKET_INDICES:
            code = config["code"]
            current = refreshed_by_code.get(code)
            cached = cached_by_code.get(code)
            if not current:
                if cached:
                    merged.append({**cached, "name": config["name"], "stale": True})
                continue

            intraday = sample_sparkline(current.get("intraday") or [], SPARKLINE_POINTS)
            intraday_cached = False
            if not intraday and cached and cached.get("intraday"):
                intraday = cached["intraday"]
                intraday_cached = True
            merged.append(
                {
                    **current,
                    "code": code,
                    "name": config["name"],
                    "intraday": intraday,
                    "intraday_cached": intraday_cached,
                    "stale": False,
                }
            )
        self.market_indices = merged


    # ── Snapshots ──

    def save_snapshot(self) -> str:
        """Save current stocks payload as a snapshot. Returns snapshot ID (timestamp)."""
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(SH_TZ).strftime("%Y%m%dT%H%M%S")
        dashboard = self.dashboard()
        payload = {
            "schema_version": 2,
            "taxonomy_version": taxonomy.version,
            "id": ts,
            "created_at": now_iso(),
            "summary": dashboard.get("summary", {}),
            "group_stats": dashboard.get("group_stats", {}),
            "scope_stats": dashboard.get("scope_stats", {}),
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
            "kline_count": self.history_store.count_codes(),
            "indicator_count": has_indicators,
            "intraday_count": has_intraday,
            "market_index_count": len(getattr(self, "market_indices", [])),
            "last_refresh_at": self.last_refresh_at,
            "last_success_at": self.last_success_at,
            "cache_path": str(CACHE_PATH),
            "db_path": str(DB_PATH),
            "history": self.history_refresh_status(),
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


def service_log(message: str) -> None:
    print(f"[{now_iso()}] {message}", file=sys.stderr, flush=True)


radar_service = RadarService()
