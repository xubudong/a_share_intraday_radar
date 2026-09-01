from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import ROOT_DIR, StockConfig, load_stock_pool


try:
    SH_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover - Windows embeddable runtimes may not include tzdata.
    SH_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


SENTIMENT_DIR = ROOT_DIR / "data" / "sentiment"
MARKS_PATH = ROOT_DIR / "data" / "sentiment_marks.json"
WALLSTREETCN_LIVES_URL = "https://api-prod.wallstreetcn.com/apiv1/content/lives"
DEFAULT_MAX_WORKERS = 8
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class SourceResult:
    name: str
    status: str
    elapsed_sec: float
    items: list[dict[str, Any]]
    error: str = ""
    attempts: int = 1


def clean_html_text(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_target_date(value: str | None) -> date:
    if not value:
        return datetime.now(SH_TZ).date()
    if not DATE_PATTERN.fullmatch(value):
        raise ValueError("日期格式必须为 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期无效") from exc


def now_iso() -> str:
    return datetime.now(SH_TZ).isoformat(timespec="seconds")


def ensure_jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {str(key): ensure_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [ensure_jsonable(item) for item in value]
    if hasattr(value, "to_dict"):
        try:
            return ensure_jsonable(value.to_dict())
        except Exception:
            pass
    return value


def run_source(
    name: str,
    fetcher: Callable[[], list[dict[str, Any]]],
    *,
    retries: int = 2,
    retry_delay: float = 1.0,
) -> SourceResult:
    start = time.perf_counter()
    attempts = max(1, retries + 1)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            items = fetcher()
            return SourceResult(
                name=name,
                status="ok",
                elapsed_sec=round(time.perf_counter() - start, 3),
                items=items,
                attempts=attempt,
            )
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(retry_delay * attempt)
    return SourceResult(
        name=name,
        status="error",
        elapsed_sec=round(time.perf_counter() - start, 3),
        items=[],
        error=f"{type(last_error).__name__}: {last_error}",
        attempts=attempts,
    )


def day_timestamp_window(target_date: date) -> tuple[int, int]:
    start = datetime.combine(target_date, datetime_time.min, tzinfo=SH_TZ)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())


def fetch_wallstreetcn_lives_page(
    channel: str,
    *,
    page_size: int,
    timeout: int,
    cursor: int | None = None,
) -> dict[str, Any]:
    import requests

    params: dict[str, Any] = {"channel": channel, "client": "pc", "limit": page_size}
    if cursor is not None:
        params["cursor"] = cursor
    response = requests.get(
        WALLSTREETCN_LIVES_URL,
        params=params,
        headers={
            "accept": "application/json,text/plain,*/*",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/142.0.0.0 Safari/537.36"
            ),
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def normalize_wallstreetcn_lives(
    items: list[dict[str, Any]],
    channel: str,
    limit: int,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items[:limit]:
        display_time = item.get("display_time")
        published_at = None
        if isinstance(display_time, int):
            published_at = datetime.fromtimestamp(display_time, SH_TZ).isoformat(timespec="seconds")
        normalized.append(
            {
                "title": item.get("title") or "",
                "content": clean_html_text(item.get("content")),
                "published_at": published_at,
                "source": "wallstreetcn_lives",
                "channel": channel,
                "symbols": item.get("symbols") or [],
                "raw": ensure_jsonable(item),
            }
        )
    return normalized


def fetch_wallstreetcn_lives(
    channel: str,
    target_date: date,
    *,
    limit: int,
    timeout: int,
    page_size: int = 50,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    start_ts, end_ts = day_timestamp_window(target_date)
    cursor: int | None = None
    collected: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()

    for _ in range(max_pages):
        payload = fetch_wallstreetcn_lives_page(
            channel,
            page_size=page_size,
            timeout=timeout,
            cursor=cursor,
        )
        data = payload.get("data", {})
        page_items = data.get("items", []) if isinstance(data, dict) else []
        if not page_items:
            break

        oldest_display_time: int | None = None
        for item in page_items:
            display_time = item.get("display_time")
            if not isinstance(display_time, int):
                continue
            oldest_display_time = (
                display_time
                if oldest_display_time is None
                else min(oldest_display_time, display_time)
            )
            item_id = item.get("id")
            if start_ts <= display_time < end_ts and item_id not in seen_ids:
                collected.append(item)
                seen_ids.add(item_id)

        if len(collected) >= limit:
            break
        if oldest_display_time is not None and oldest_display_time < start_ts:
            break

        next_cursor = parse_int(data.get("next_cursor")) if isinstance(data, dict) else None
        if next_cursor is None or next_cursor == cursor:
            break
        cursor = next_cursor

    return normalize_wallstreetcn_lives(collected, channel, limit)


def fetch_levistock_market_emotion() -> list[dict[str, Any]]:
    import levistock as ls

    return [ensure_jsonable(ls.market_emotion_cls())]


def fetch_levistock_market_wind(limit: int) -> list[dict[str, Any]]:
    import levistock as ls

    return [ensure_jsonable(item) for item in ls.market_wind_cls()[:limit]]


def fetch_levistock_sector_heat(limit: int) -> list[dict[str, Any]]:
    import levistock as ls

    return [ensure_jsonable(item) for item in ls.get_sector_heat()[:limit]]


def fetch_levistock_zttt() -> list[dict[str, Any]]:
    import levistock as ls

    return [ensure_jsonable(ls.get_zttt())]


def fetch_levistock_telegraph(limit: int) -> list[dict[str, Any]]:
    import levistock as ls

    return [ensure_jsonable(item) for item in ls.news_telegraph_cls()[:limit]]


def fetch_zzshare_review_uplimit(limit: int) -> list[dict[str, Any]]:
    import zzshare as zz

    return [ensure_jsonable(item) for item in zz.review_uplimit_reason_open()[:limit]]


def fetch_zzshare_ai_report(limit: int) -> list[dict[str, Any]]:
    import zzshare as zz

    payload = zz.ai_report_list()
    if isinstance(payload, dict):
        return [ensure_jsonable(item) for item in payload.get("items", [])[:limit]]
    return [ensure_jsonable(payload)]


def fetch_zzshare_market_sentiment(limit: int) -> list[dict[str, Any]]:
    import zzshare as zz

    return [ensure_jsonable(item) for item in zz.market_sentiment()[-limit:]]


def collect_daily_sentiment(
    target_date: date,
    *,
    limit: int = 500,
    include_telegraph: bool = False,
    timeout: int = 15,
    max_workers: int = DEFAULT_MAX_WORKERS,
    retries: int = 2,
    retry_delay: float = 1.0,
) -> list[SourceResult]:
    sources: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
        (
            "wallstreetcn_global",
            lambda: fetch_wallstreetcn_lives(
                "global-channel",
                target_date,
                limit=limit,
                timeout=timeout,
            ),
        ),
        (
            "wallstreetcn_a_stock",
            lambda: fetch_wallstreetcn_lives(
                "a-stock-channel",
                target_date,
                limit=limit,
                timeout=timeout,
            ),
        ),
        ("levistock_market_emotion", fetch_levistock_market_emotion),
        ("levistock_market_wind", lambda: fetch_levistock_market_wind(limit=20)),
        ("levistock_sector_heat", lambda: fetch_levistock_sector_heat(limit=30)),
        ("levistock_zttt", fetch_levistock_zttt),
        ("zzshare_review_uplimit", lambda: fetch_zzshare_review_uplimit(limit=80)),
        ("zzshare_ai_report", lambda: fetch_zzshare_ai_report(limit=5)),
        ("zzshare_market_sentiment", lambda: fetch_zzshare_market_sentiment(limit=30)),
    ]
    if include_telegraph:
        sources.insert(6, ("levistock_telegraph", lambda: fetch_levistock_telegraph(limit=limit)))

    results_by_name: dict[str, SourceResult] = {}
    workers = max(1, min(max_workers, len(sources)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                run_source,
                name,
                fetcher,
                retries=retries,
                retry_delay=retry_delay,
            ): name
            for name, fetcher in sources
        }
        for future in as_completed(futures):
            name = futures[future]
            results_by_name[name] = future.result()
    return [results_by_name[name] for name, _ in sources]


def source_result_to_dict(result: SourceResult) -> dict[str, Any]:
    return {
        "name": result.name,
        "status": result.status,
        "elapsed_sec": result.elapsed_sec,
        "item_count": len(result.items),
        "items": result.items,
        "error": result.error,
        "attempts": result.attempts,
    }


def build_payload(
    target_date: date,
    results: list[SourceResult],
    *,
    generated_at: datetime | None = None,
    total_elapsed_sec: float | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(SH_TZ)
    return {
        "target_date": target_date.isoformat(),
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "total_elapsed_sec": total_elapsed_sec,
        "source_summary": [
            {
                "name": result.name,
                "status": result.status,
                "elapsed_sec": result.elapsed_sec,
                "item_count": len(result.items),
                "error": result.error,
                "attempts": result.attempts,
            }
            for result in results
        ],
        "sources": [source_result_to_dict(result) for result in results],
    }


def sentiment_payload_path(target_date: date | str) -> Path:
    date_text = target_date if isinstance(target_date, str) else target_date.isoformat()
    return SENTIMENT_DIR / date_text / "payload.json"


def write_payload(payload: dict[str, Any]) -> Path:
    path = sentiment_payload_path(str(payload["target_date"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
    return path


def read_payload(target_date: date) -> dict[str, Any] | None:
    path = sentiment_payload_path(target_date)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


class SentimentMarkStore:
    """保存人工重点标记。自动命中不写入这里。"""

    def __init__(self, path: Path = MARKS_PATH) -> None:
        self._path = path
        self._lock = threading.RLock()

    def marked_ids(self) -> set[str]:
        with self._lock:
            return set(self._read().get("marks", []))

    def is_marked(self, item_id: str) -> bool:
        return item_id in self.marked_ids()

    def toggle(self, item_id: str) -> bool:
        if not re.fullmatch(r"[0-9a-f]{16,64}", item_id):
            raise ValueError("消息 ID 无效")
        with self._lock:
            data = self._read()
            marks = set(data.get("marks", []))
            if item_id in marks:
                marks.discard(item_id)
            else:
                marks.add(item_id)
            self._write({"version": 1, "marks": sorted(marks)})
            return item_id in marks

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"version": 1, "marks": []}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("无法读取舆情标记文件，请先检查文件内容") from exc
        if not isinstance(data, dict) or not isinstance(data.get("marks", []), list):
            raise RuntimeError("舆情标记文件格式无效")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self._path)


def item_stable_id(source: str, published_at: str | None, title: str, content: str) -> str:
    base = "\n".join([source, published_at or "", title or "", content or ""])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


def compact_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) > limit:
        return f"{text[:limit]}..."
    return text


GROUP_ALIAS_OVERRIDES: dict[str, tuple[str, ...]] = {
    "电子元件-PCB/FPC": ("PCB", "FPC", "软板"),
    "电子元件-PCB设备": ("PCB设备", "PCB装备", "PCB数控", "LDI", "直接成像", "PCB钻针", "FPC测试"),
    "电子元件-覆铜板": ("覆铜板",),
    "电子元件-电子铜箔": ("铜箔", "电子铜箔"),
    "电子元件-MLCC/被动元件": ("MLCC", "被动元件"),
    "电子元件-玻璃基板": ("玻璃基板",),
    "电子元件-玻璃玻纤/电子布": ("玻璃玻纤", "电子布"),
    "化工-工业气体": ("工业气体",),
    "半导体芯片-存储": ("存储芯片", "存储"),
    "先进封装-封测厂": ("先进封装", "封测厂"),
    "机器人-本体/核心零部件": ("机器人核心", "机器人本体", "核心零部件"),
    "算力基础设施-液冷": ("液冷核心", "液冷"),
    "国产算力-算力租赁/智算运营": ("算力租赁", "智算运营", "算力服务", "IaaS算力"),
}


def group_alias_terms(group: str) -> list[str]:
    terms = [group, *GROUP_ALIAS_OVERRIDES.get(group, ())]
    return list(dict.fromkeys(term for term in terms if term))


def build_match_index(pool: list[StockConfig]) -> dict[str, Any]:
    stocks_by_code = {stock.code: stock for stock in pool}
    stock_terms: list[tuple[str, StockConfig, str]] = []
    group_terms: dict[str, str] = {}

    for stock in pool:
        stock_terms.append((stock.code, stock, "代码"))
        stock_terms.append((stock.name, stock, "名称"))
        if stock.note:
            for term in split_note_terms(stock.note):
                stock_terms.append((term, stock, "备注"))
        for group in stock.groups:
            for term in group_alias_terms(group):
                group_terms[term] = group

    dedup_stock_terms: dict[tuple[str, str, str], tuple[str, StockConfig, str]] = {}
    for term, stock, reason in stock_terms:
        term = str(term or "").strip()
        if len(term) < 2:
            continue
        dedup_stock_terms[(term, stock.code, reason)] = (term, stock, reason)
    return {
        "stocks_by_code": stocks_by_code,
        "stock_terms": list(dedup_stock_terms.values()),
        "group_terms": sorted(group_terms.items(), key=lambda item: (-len(item[0]), item[0])),
    }


def split_note_terms(note: str) -> list[str]:
    raw_terms = re.split(r"[/,，;；、\s]+", note)
    terms = [term.strip() for term in raw_terms if len(term.strip()) >= 2]
    for term in list(terms):
        without_prefix = re.sub(r"^[A-Za-z0-9]+", "", term).strip()
        if len(without_prefix) >= 2:
            terms.append(without_prefix)
    note = note.strip()
    if len(note) >= 2:
        terms.append(note)
    return list(dict.fromkeys(terms))


def match_stock_pool(text: str, match_index: dict[str, Any]) -> dict[str, Any]:
    matched_stocks: dict[str, dict[str, Any]] = {}
    matched_groups: set[str] = set()
    match_reasons: list[str] = []

    for term, stock, reason in match_index["stock_terms"]:
        if term and term in text:
            if stock.code not in matched_stocks:
                matched_stocks[stock.code] = {
                    "code": stock.code,
                    "name": stock.name,
                    "group": stock.group,
                    "groups": list(stock.groups),
                    "tier": stock.tier,
                }
            match_reasons.append(f"{reason}命中：{term}")
            matched_groups.update(stock.groups)

    for term, group in match_index["group_terms"]:
        if term and term in text:
            matched_groups.add(group)
            match_reasons.append(f"板块命中：{term}")

    return {
        "matched_stocks": sorted(matched_stocks.values(), key=lambda item: item["code"]),
        "matched_groups": sorted(matched_groups),
        "match_reasons": list(dict.fromkeys(match_reasons))[:20],
    }


def item_text(*parts: Any) -> str:
    return " ".join(compact_text(part, 2000) for part in parts if part is not None)


def source_label(name: str) -> str:
    labels = {
        "wallstreetcn_global": "华尔街见闻·全球",
        "wallstreetcn_a_stock": "华尔街见闻·A股",
        "levistock_telegraph": "财联社电报",
        "levistock_market_emotion": "市场情绪",
        "levistock_market_wind": "今日风口",
        "levistock_sector_heat": "板块热度",
        "levistock_zttt": "涨停天梯",
        "zzshare_review_uplimit": "涨停原因",
        "zzshare_ai_report": "AI主题摘要",
        "zzshare_market_sentiment": "情绪序列",
    }
    return labels.get(name, name)


def build_timeline_item(
    source_name: str,
    item: dict[str, Any],
    match_index: dict[str, Any],
    marks: set[str],
) -> dict[str, Any]:
    title = str(item.get("title") or item.get("标题") or item.get("plate_name") or "")
    content = str(
        item.get("content")
        or item.get("摘要")
        or item.get("summary")
        or item.get("catalyst")
        or ""
    )
    published_at = item.get("published_at") or item.get("time") or item.get("发布时间")
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
    importance_score = item.get("score", raw.get("score"))
    try:
        importance_score = int(importance_score) if importance_score is not None else None
    except (TypeError, ValueError):
        importance_score = None
    item_id = item_stable_id(source_name, str(published_at or ""), title, content)
    matches = match_stock_pool(item_text(title, content), match_index)
    return {
        "id": item_id,
        "source": source_name,
        "source_label": source_label(source_name),
        "published_at": published_at,
        "title": title,
        "content": content,
        "importance_score": importance_score,
        "importance_label": importance_label(importance_score),
        "manual_marked": item_id in marks,
        "auto_matched": bool(matches["matched_stocks"] or matches["matched_groups"]),
        "matched_stocks": matches["matched_stocks"],
        "matched_groups": matches["matched_groups"],
        "match_reasons": matches["match_reasons"],
        "raw": item,
    }


def importance_label(score: int | None) -> str:
    if score is None:
        return ""
    if score >= 3:
        return "重要"
    if score == 2:
        return "重点"
    return "普通"


def timeline_duplicate_key(item: dict[str, Any]) -> str:
    title = compact_text(item.get("title"), 2000)
    content = compact_text(item.get("content"), 4000)
    if title or content:
        return hashlib.sha1(f"{title}\n{content}".encode("utf-8")).hexdigest()
    return str(item.get("id") or "")


def dedupe_timeline_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate same-day duplicated news across channels while keeping richer source labels."""
    by_key: dict[str, dict[str, Any]] = {}
    for item in items:
        key = timeline_duplicate_key(item)
        current = by_key.get(key)
        if current is None:
            by_key[key] = item
            continue
        sources = set(current.get("duplicate_sources") or [current.get("source_label") or current.get("source")])
        sources.add(item.get("source_label") or item.get("source"))
        current["duplicate_sources"] = sorted(source for source in sources if source)
        current["duplicate_count"] = len(current["duplicate_sources"])
        if item.get("source") == "wallstreetcn_a_stock" and current.get("source") != "wallstreetcn_a_stock":
            item["duplicate_sources"] = current["duplicate_sources"]
            item["duplicate_count"] = current["duplicate_count"]
            by_key[key] = item
    return list(by_key.values())


def build_market_sections(
    payload: dict[str, Any],
    match_index: dict[str, Any],
) -> list[dict[str, Any]]:
    source_map = {source["name"]: source for source in payload.get("sources", [])}
    sections: list[dict[str, Any]] = []

    def add_section(name: str, title: str, items: list[dict[str, Any]]) -> None:
        rendered = []
        for item in items:
            text = json.dumps(item, ensure_ascii=False)
            matches = match_stock_pool(text, match_index)
            rendered.append(
                {
                    "text": section_item_text(name, item),
                    "raw": item,
                    "auto_matched": bool(matches["matched_stocks"] or matches["matched_groups"]),
                    "matched_stocks": matches["matched_stocks"],
                    "matched_groups": matches["matched_groups"],
                    "match_reasons": matches["match_reasons"],
                }
            )
        sections.append({"name": name, "title": title, "items": rendered})

    add_section(
        "levistock_market_emotion",
        "市场情绪",
        source_map.get("levistock_market_emotion", {}).get("items", []),
    )
    add_section(
        "levistock_market_wind",
        "今日风口",
        source_map.get("levistock_market_wind", {}).get("items", []),
    )
    add_section(
        "levistock_sector_heat",
        "板块热度",
        source_map.get("levistock_sector_heat", {}).get("items", []),
    )
    add_section(
        "levistock_zttt",
        "涨停天梯",
        source_map.get("levistock_zttt", {}).get("items", []),
    )
    add_section(
        "zzshare_review_uplimit",
        "涨停原因",
        source_map.get("zzshare_review_uplimit", {}).get("items", []),
    )
    add_section(
        "zzshare_ai_report",
        "AI主题摘要",
        source_map.get("zzshare_ai_report", {}).get("items", []),
    )
    add_section(
        "zzshare_market_sentiment",
        "市场情绪序列",
        source_map.get("zzshare_market_sentiment", {}).get("items", [])[-10:],
    )
    return sections


def section_item_text(source_name: str, item: dict[str, Any]) -> str:
    if source_name == "levistock_market_emotion":
        return "；".join(
            part
            for part in [
                f"市场热度：{item.get('market_degree', '')}",
                f"上涨占比：{item.get('up_ratio', '')}",
                f"赚钱效应：{item.get('profit_ratio', '')}",
            ]
            if not part.endswith("：")
        ) or compact_text(json.dumps(item, ensure_ascii=False), 350)
    if source_name == "levistock_market_wind":
        return f"{item.get('plate_name', '')}：{compact_text(item.get('catalyst', ''), 350)}"
    if source_name == "levistock_sector_heat":
        rank = item.get("rank")
        prefix = f"{rank}. " if rank else ""
        return f"{prefix}{item.get('plate_name', '')}".strip() or compact_text(json.dumps(item, ensure_ascii=False), 350)
    if source_name == "levistock_zttt":
        stock_list = item.get("StockList") or []
        samples = []
        for stock in stock_list[:30]:
            if isinstance(stock, list) and len(stock) >= 6:
                samples.append(f"{stock[0]} {stock[1]} {stock[2]}板 {stock[5]}")
        return "；".join(samples) if samples else compact_text(json.dumps(item, ensure_ascii=False), 600)
    if source_name == "zzshare_review_uplimit":
        return f"{item.get('stock_code', '')} {item.get('stock_name', '')}：{compact_text(item.get('reason', ''), 500)}"
    if source_name == "zzshare_ai_report":
        concepts = item.get("concepts") or []
        suffix = "；".join(str(concept) for concept in concepts[:5])
        return f"{item.get('title', '')}：{suffix}" if suffix else str(item.get("title") or "")
    if source_name == "zzshare_market_sentiment":
        keys = ["date", "p_close", "p_high", "p_low"]
        return " ".join(f"{key}={item.get(key)}" for key in keys if key in item)
    return compact_text(json.dumps(item, ensure_ascii=False), 500)


def derive_display_payload(
    payload: dict[str, Any],
    *,
    marks: set[str] | None = None,
    pool: list[StockConfig] | None = None,
) -> dict[str, Any]:
    marks = marks or set()
    match_index = build_match_index(pool or load_stock_pool())
    timeline_sources = {
        "wallstreetcn_global",
        "wallstreetcn_a_stock",
        "levistock_telegraph",
    }
    timeline: list[dict[str, Any]] = []
    for source in payload.get("sources", []):
        source_name = source.get("name", "")
        if source_name not in timeline_sources:
            continue
        for item in source.get("items", []):
            timeline.append(build_timeline_item(source_name, item, match_index, marks))
    timeline = dedupe_timeline_items(timeline)

    timeline.sort(
        key=lambda item: (
            str(item.get("published_at") or ""),
            item.get("source", ""),
            item.get("id", ""),
        ),
        reverse=True,
    )
    return {
        "status": "ok",
        "target_date": payload.get("target_date"),
        "generated_at": payload.get("generated_at"),
        "total_elapsed_sec": payload.get("total_elapsed_sec"),
        "source_summary": payload.get("source_summary", []),
        "timeline": timeline,
        "market_sections": build_market_sections(payload, match_index),
        "summary": {
            "timeline_count": len(timeline),
            "manual_marked": sum(1 for item in timeline if item.get("manual_marked")),
            "auto_matched": sum(1 for item in timeline if item.get("auto_matched")),
            "source_count": len(payload.get("sources", [])),
            "error_count": sum(1 for item in payload.get("source_summary", []) if item.get("status") != "ok"),
        },
    }


class SentimentService:
    def __init__(self) -> None:
        self._refresh_state_lock = threading.RLock()
        self._refreshing = False
        self._pending: dict[str, Any] | None = None
        self._refresh_thread: threading.Thread | None = None
        self._last_refresh_mode = "none"
        self._last_refresh_at: str | None = None
        self._last_error: str = ""
        self.mark_store = SentimentMarkStore()

    def get_sentiment(self, target_date_text: str | None = None) -> dict[str, Any]:
        target_date = parse_target_date(target_date_text)
        try:
            payload = read_payload(target_date)
        except Exception as exc:
            raise RuntimeError("无法读取舆情缓存文件") from exc
        if payload is None:
            return {
                "status": "missing",
                "target_date": target_date.isoformat(),
                "generated_at": None,
                "total_elapsed_sec": None,
                "source_summary": [],
                "timeline": [],
                "market_sections": [],
                "summary": {
                    "timeline_count": 0,
                    "manual_marked": 0,
                    "auto_matched": 0,
                    "source_count": 0,
                    "error_count": 0,
                },
                "refresh": self.refresh_status(),
            }
        data = derive_display_payload(payload, marks=self.mark_store.marked_ids())
        data["refresh"] = self.refresh_status()
        return data

    def start_refresh(
        self,
        *,
        target_date_text: str | None = None,
        profile: str = "fast",
        include_telegraph: bool = False,
    ) -> dict[str, Any]:
        if profile != "fast":
            raise ValueError("当前仅支持 fast 模式")
        target_date = parse_target_date(target_date_text)
        request = {
            "target_date": target_date,
            "profile": profile,
            "include_telegraph": include_telegraph,
        }
        with self._refresh_state_lock:
            if self._refreshing:
                self._pending = request
                return self.refresh_status(accepted=False)
            self._refreshing = True
            self._pending = None
            thread = threading.Thread(target=self._run_refresh_queue, args=(request,), daemon=True)
            self._refresh_thread = thread
            thread.start()
            return self.refresh_status(accepted=True)

    def _run_refresh_queue(self, request: dict[str, Any]) -> None:
        current = request
        while True:
            try:
                self.refresh(
                    target_date=current["target_date"],
                    include_telegraph=bool(current.get("include_telegraph")),
                )
            except Exception as exc:  # pragma: no cover - last-resort worker protection
                self._last_error = str(exc)
            with self._refresh_state_lock:
                if self._pending is not None:
                    current = self._pending
                    self._pending = None
                    continue
                self._refreshing = False
                self._refresh_thread = None
                return

    def refresh(self, *, target_date: date, include_telegraph: bool = False) -> dict[str, Any]:
        started = time.perf_counter()
        self._last_refresh_at = now_iso()
        self._last_refresh_mode = "manual"
        self._last_error = ""
        results = collect_daily_sentiment(
            target_date,
            include_telegraph=include_telegraph,
        )
        total_elapsed_sec = round(time.perf_counter() - started, 3)
        payload = build_payload(target_date, results, total_elapsed_sec=total_elapsed_sec)
        write_payload(payload)
        return derive_display_payload(payload, marks=self.mark_store.marked_ids())

    def refresh_status(self, accepted: bool | None = None) -> dict[str, Any]:
        with self._refresh_state_lock:
            status = {
                "refreshing": self._refreshing,
                "pending": self._pending is not None,
                "mode": self._last_refresh_mode,
                "last_refresh_at": self._last_refresh_at,
                "last_error": self._last_error,
            }
            if accepted is not None:
                status["accepted"] = accepted
            return status

    def toggle_mark(self, item_id: str) -> dict[str, Any]:
        marked = self.mark_store.toggle(item_id)
        return {"id": item_id, "manual_marked": marked}


sentiment_service = SentimentService()
