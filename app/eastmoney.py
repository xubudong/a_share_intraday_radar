from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any

from .config import eastmoney_secid


QUOTE_FIELDS = "f2,f3,f4,f5,f6,f12,f13,f14,f15,f16,f17,f18,f20,f21,f62,f184"
KLINE_FIELDS1 = "f1,f2,f3,f4,f5,f6"
KLINE_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
INDEX_QUOTE_FIELDS = "f2,f3,f4,f12,f14,f15,f16,f17,f18"
MARKET_INDICES = [
    {"code": "000001", "name": "上证指数", "secid": "1.000001", "symbol": "sh000001"},
    {"code": "399001", "name": "深证成指", "secid": "0.399001", "symbol": "sz399001"},
    {"code": "399006", "name": "创业板指", "secid": "0.399006", "symbol": "sz399006"},
]


class EastMoneyError(RuntimeError):
    pass


def request_json(url: str, timeout: int = 10, allow_code_zero: bool = False) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read().decode("utf-8", "ignore")
    data = json.loads(payload)
    if allow_code_zero and data.get("code") == 0:
        return data
    if data.get("rc") not in (0, None):
        raise EastMoneyError(f"EastMoney rc={data.get('rc')}")
    return data


def fetch_realtime_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}

    quotes: dict[str, dict[str, Any]] = {}
    last_error: Exception | None = None
    consecutive_failures = 0
    for chunk in chunks(codes, 24):
        secids = ",".join(eastmoney_secid(code) for code in chunk)
        params = {
            "fltt": "2",
            "invt": "2",
            "fields": QUOTE_FIELDS,
            "secids": secids,
        }
        url = "https://push2.eastmoney.com/api/qt/ulist.np/get?" + urllib.parse.urlencode(params)
        try:
            data = request_json(url, timeout=12)
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
            try:
                data = request_json(url, timeout=12)
            except Exception as retry_exc:
                last_error = retry_exc
                consecutive_failures += 1
                if consecutive_failures >= 2:
                    break
                continue
        consecutive_failures = 0
        rows = data.get("data", {}).get("diff") or []
        for row in rows:
            code = str(row.get("f12")).zfill(6)
            price = clean_number(row.get("f2"))
            prev_close = clean_number(row.get("f18"))
            quotes[code] = {
                "code": code,
                "name": row.get("f14"),
                "price": price,
                "pct_chg": clean_number(row.get("f3")),
                "change": clean_number(row.get("f4")),
                "volume": clean_number(row.get("f5")),
                "amount": clean_number(row.get("f6")),
                "high": clean_number(row.get("f15")),
                "low": clean_number(row.get("f16")),
                "open": clean_number(row.get("f17")),
                "prev_close": prev_close,
                "turnover_market_cap": clean_number(row.get("f21")),
                "main_net_inflow": clean_number(row.get("f62")),
                "main_net_inflow_pct": clean_number(row.get("f184")),
                "source": "eastmoney_realtime",
                "updated_at": int(time.time()),
            }

    missing_codes = [code for code in codes if code not in quotes]
    if missing_codes:
        try:
            quotes.update(fetch_tencent_realtime_quotes(missing_codes))
        except Exception as exc:
            last_error = exc

    if not quotes:
        raise EastMoneyError(str(last_error) if last_error else "Realtime quote response was empty")
    return quotes


def fetch_market_indices() -> list[dict[str, Any]]:
    """Fetch major A-share index quotes with intraday sparklines."""
    index_by_code = {index["code"]: index for index in MARKET_INDICES}
    last_error: Exception | None = None
    try:
        quotes = fetch_eastmoney_market_index_quotes()
    except Exception as exc:
        last_error = exc
        quotes = {}

    missing_indices = [
        index
        for index in MARKET_INDICES
        if index["code"] not in quotes
    ]
    if missing_indices:
        try:
            quotes.update(fetch_tencent_market_index_quotes(missing_indices))
        except Exception as exc:
            last_error = exc

    results: list[dict[str, Any]] = []
    for index in MARKET_INDICES:
        quote = quotes.get(index["code"])
        if not quote:
            continue
        try:
            intraday = fetch_market_index_intraday(index)
        except Exception:
            intraday = []
        results.append(
            {
                **quote,
                "code": index["code"],
                "symbol": index["symbol"],
                "name": quote.get("name") or index_by_code[index["code"]]["name"],
                "intraday": intraday,
            }
        )

    if not results and last_error:
        raise EastMoneyError(str(last_error))
    return results


def fetch_eastmoney_market_index_quotes() -> dict[str, dict[str, Any]]:
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": INDEX_QUOTE_FIELDS,
        "secids": ",".join(index["secid"] for index in MARKET_INDICES),
    }
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get?" + urllib.parse.urlencode(params)
    data = request_json(url, timeout=12)
    rows = data.get("data", {}).get("diff") or []
    quotes: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("f12") or "").zfill(6)
        price = clean_number(row.get("f2"))
        if not code or price is None:
            continue
        quotes[code] = {
            "code": code,
            "name": row.get("f14"),
            "price": price,
            "pct_chg": clean_number(row.get("f3")),
            "change": clean_number(row.get("f4")),
            "high": clean_number(row.get("f15")),
            "low": clean_number(row.get("f16")),
            "open": clean_number(row.get("f17")),
            "prev_close": clean_number(row.get("f18")),
            "source": "eastmoney_index",
            "updated_at": int(time.time()),
        }
    if not quotes:
        raise EastMoneyError("EastMoney index quote response was empty")
    return quotes


def fetch_tencent_market_index_quotes(indices: list[dict[str, str]] | None = None) -> dict[str, dict[str, Any]]:
    selected = indices or MARKET_INDICES
    symbols = ",".join(index["symbol"] for index in selected)
    url = "https://qt.gtimg.cn/q=" + urllib.parse.quote(symbols, safe=",")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://gu.qq.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        payload = response.read().decode("gbk", "ignore")
    quotes: dict[str, dict[str, Any]] = {}
    for line in payload.splitlines():
        quote = parse_tencent_quote(line)
        if not quote:
            continue
        quote["source"] = "tencent_index"
        quotes[quote["code"]] = quote
    if not quotes:
        raise EastMoneyError("Tencent index quote response was empty")
    return quotes


def fetch_market_index_intraday(index: dict[str, str]) -> list[float]:
    try:
        prices = fetch_eastmoney_intraday_trends_by_secid(index["secid"])
        if prices:
            return prices
    except Exception:
        pass
    return fetch_tencent_intraday_trends_by_symbol(index["symbol"])


def fetch_tencent_realtime_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    last_error: Exception | None = None
    for chunk in chunks(codes, 50):
        symbols = ",".join(tencent_symbol(code) for code in chunk)
        url = "https://qt.gtimg.cn/q=" + urllib.parse.quote(symbols, safe=",")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://gu.qq.com/",
            },
        )
        payload = ""
        for attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=12) as response:
                    payload = response.read().decode("gbk", "ignore")
                break
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.2)
        if not payload:
            continue
        for line in payload.splitlines():
            quote = parse_tencent_quote(line)
            if quote:
                quotes[quote["code"]] = quote

    if not quotes:
        raise EastMoneyError(str(last_error) if last_error else "Tencent quote response was empty")
    return quotes


def parse_tencent_quote(line: str) -> dict[str, Any] | None:
    _, marker, payload = line.partition('="')
    if not marker:
        return None
    fields = payload.rstrip('";\r\n').split("~")
    if len(fields) <= 45:
        return None

    code = fields[2].zfill(6)
    price = clean_number(fields[3])
    if not code or price is None:
        return None

    amount_parts = fields[35].split("/") if len(fields) > 35 else []
    amount = clean_number(amount_parts[2]) if len(amount_parts) > 2 else None
    market_cap = clean_number(fields[45])
    return {
        "code": code,
        "name": fields[1],
        "price": price,
        "pct_chg": clean_number(fields[32]),
        "change": clean_number(fields[31]),
        "volume": clean_number(fields[36]),
        "amount": amount,
        "high": clean_number(fields[33]),
        "low": clean_number(fields[34]),
        "open": clean_number(fields[5]),
        "prev_close": clean_number(fields[4]),
        "turnover_market_cap": market_cap * 100000000 if market_cap is not None else None,
        "main_net_inflow": None,
        "main_net_inflow_pct": None,
        "source": "tencent_realtime",
        "quote_time": fields[30],
        "updated_at": int(time.time()),
    }


def fetch_daily_klines(code: str, limit: int = 180) -> list[dict[str, Any]]:
    try:
        return fetch_eastmoney_daily_klines(code, limit=limit)
    except Exception:
        return fetch_tencent_daily_klines(code, limit=limit)


def fetch_eastmoney_daily_klines(code: str, limit: int = 180) -> list[dict[str, Any]]:
    params = {
        "secid": eastmoney_secid(code),
        "fields1": KLINE_FIELDS1,
        "fields2": KLINE_FIELDS2,
        "klt": "101",
        "fqt": "1",
        "beg": "20240101",
        "end": "20500101",
        "lmt": str(limit),
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    }
    query = urllib.parse.urlencode(params)
    urls = [
        "http://push2his.eastmoney.com/api/qt/stock/kline/get?" + query,
        "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + query,
    ]
    last_error: Exception | None = None
    for url in urls:
        try:
            data = request_json(url, timeout=12)
            break
        except Exception as exc:
            last_error = exc
    else:
        raise EastMoneyError(str(last_error))
    lines = data.get("data", {}).get("klines") or []
    rows = []
    for line in lines:
        parts = line.split(",")
        if len(parts) < 11:
            continue
        rows.append(
            {
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
                "amplitude": float(parts[7]),
                "pct_chg": float(parts[8]),
                "change": float(parts[9]),
                "turnover": float(parts[10]),
            }
        )
    return rows


def fetch_intraday_trends(code: str) -> list[float]:
    """Fetch today's minute prices, falling back to Tencent when needed."""
    try:
        prices = fetch_eastmoney_intraday_trends_by_secid(eastmoney_secid(code))
        if prices:
            return prices
    except Exception:
        pass
    for fetcher in (fetch_tencent_intraday_trends, fetch_sina_intraday_trends):
        try:
            prices = fetcher(code)
            if prices:
                return prices
        except Exception:
            continue
    return []


def fetch_eastmoney_intraday_trends_by_secid(secid: str) -> list[float]:
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "iscr": "0",
        "ndays": "1",
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/trends2/get?" + urllib.parse.urlencode(params)
    data = request_json(url, timeout=8)
    trends = (data.get("data") or {}).get("trends") or []
    prices: list[float] = []
    for line in trends:
        parts = line.split(",")
        if len(parts) >= 2:
            try:
                prices.append(float(parts[1]))
            except (ValueError, IndexError):
                continue
    return prices


def fetch_tencent_intraday_trends(code: str) -> list[float]:
    return fetch_tencent_intraday_trends_by_symbol(tencent_symbol(code))


def fetch_tencent_intraday_trends_by_symbol(symbol: str) -> list[float]:
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/minute/query?"
        + urllib.parse.urlencode({"code": symbol})
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://gu.qq.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        payload = response.read().decode("utf-8", "ignore")
    data = json.loads(payload)
    if data.get("code") not in (0, None):
        raise EastMoneyError(f"Tencent minute code={data.get('code')}")
    lines = (
        data.get("data", {})
        .get(symbol, {})
        .get("data", {})
        .get("data", [])
    )
    prices: list[float] = []
    for line in lines:
        parts = str(line).split()
        if len(parts) < 2:
            continue
        price = clean_number(parts[1])
        if price is not None:
            prices.append(price)
    if not prices:
        raise EastMoneyError(f"Tencent minute response was empty for {symbol}")
    return prices


def fetch_sina_intraday_trends(code: str) -> list[float]:
    symbol = tencent_symbol(code)
    params = {
        "symbol": symbol,
        "scale": "1",
        "ma": "no",
        "datalen": "241",
    }
    url = (
        "https://quotes.sina.cn/cn/api/openapi.php/"
        "CN_MarketDataService.getKLineData?"
        + urllib.parse.urlencode(params)
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn/",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        payload = response.read().decode("utf-8", "ignore")
    data = json.loads(payload)
    rows = data.get("result", {}).get("data") or []
    valid_rows = [
        row
        for row in rows
        if isinstance(row, dict) and row.get("day") and clean_number(row.get("close")) is not None
    ]
    if not valid_rows:
        raise EastMoneyError(f"Sina minute response was empty for {code}")
    latest_date = max(str(row["day"])[:10] for row in valid_rows)
    prices = [
        float(row["close"])
        for row in valid_rows
        if str(row["day"]).startswith(latest_date)
    ]
    if not prices:
        raise EastMoneyError(f"Sina minute response was empty for {code}")
    return prices


def fetch_tencent_daily_klines(code: str, limit: int = 180) -> list[dict[str, Any]]:
    symbol = tencent_symbol(code)
    params = {"param": f"{symbol},day,,,{limit},qfq"}
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + urllib.parse.urlencode(params)
    data = request_json(url, timeout=12, allow_code_zero=True)
    node = data.get("data", {}).get(symbol) or {}
    lines = node.get("qfqday") or node.get("day") or []
    rows: list[dict[str, Any]] = []
    previous_close: float | None = None
    for line in lines:
        if len(line) < 6:
            continue
        open_price = float(line[1])
        close_price = float(line[2])
        high = float(line[3])
        low = float(line[4])
        volume = float(line[5])
        pct_chg = ((close_price / previous_close - 1) * 100) if previous_close else 0
        rows.append(
            {
                "date": line[0],
                "open": open_price,
                "close": close_price,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": 0,
                "amplitude": ((high / low - 1) * 100) if low else 0,
                "pct_chg": pct_chg,
                "change": close_price - previous_close if previous_close else 0,
                "turnover": 0,
                "source": "tencent_qfqday",
            }
        )
        previous_close = close_price
    if not rows:
        raise EastMoneyError(f"Tencent kline response was empty for {code}")
    return rows


def clean_number(value: Any) -> float | None:
    if value in (None, "-", ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def tencent_symbol(code: str) -> str:
    return ("sh" if code.startswith(("5", "6", "9")) else "sz") + code
