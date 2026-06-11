from __future__ import annotations

from typing import Any


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def rolling_mean(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return mean(values[-window:])


def rsi(values: list[float], window: int = 14) -> float | None:
    if len(values) < window + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for idx in range(len(values) - window, len(values)):
        delta = values[idx] - values[idx - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = mean(gains) or 0
    avg_loss = mean(losses) or 0
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def pct(value: float | None, base: float | None) -> float | None:
    if value is None or base in (None, 0):
        return None
    return (value / base - 1) * 100


def round_or_none(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def compute_indicators(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}

    closes = [float(row["close"]) for row in rows]
    highs = [float(row["high"]) for row in rows]
    lows = [float(row["low"]) for row in rows]
    volumes = [float(row.get("volume", 0) or 0) for row in rows]
    latest = rows[-1]
    close = closes[-1]

    ma5 = rolling_mean(closes, 5)
    ma10 = rolling_mean(closes, 10)
    ma20 = rolling_mean(closes, 20)
    ma60 = rolling_mean(closes, 60)
    vol5 = rolling_mean(volumes, 5)
    vol20 = rolling_mean(volumes, 20)

    prev_closes = closes[:-1] or closes
    high20_prev = max(prev_closes[-20:]) if prev_closes else None
    high60_prev = max(prev_closes[-60:]) if prev_closes else None
    high20 = max(closes[-20:])
    high60 = max(closes[-60:])
    low20 = min(lows[-20:])

    large_candle = find_recent_large_candle(rows)

    return {
        "date": latest.get("date"),
        "ma5": round_or_none(ma5),
        "ma10": round_or_none(ma10),
        "ma20": round_or_none(ma20),
        "ma60": round_or_none(ma60),
        "dev_ma5": round_or_none(pct(close, ma5)),
        "dev_ma10": round_or_none(pct(close, ma10)),
        "dev_ma20": round_or_none(pct(close, ma20)),
        "dev_ma60": round_or_none(pct(close, ma60)),
        "rsi14": round_or_none(rsi(closes, 14)),
        "volume_ratio": round_or_none(vol5 / vol20 if vol5 and vol20 else None),
        "high20": round_or_none(high20),
        "high60": round_or_none(high60),
        "high20_prev": round_or_none(high20_prev),
        "high60_prev": round_or_none(high60_prev),
        "low20": round_or_none(low20),
        "from_high20": round_or_none(pct(close, high20)),
        "from_high60": round_or_none(pct(close, high60)),
        "large_candle": large_candle,
        "uptrend": bool(ma5 and ma10 and ma20 and ma60 and close > ma20 and ma5 > ma10 > ma20 > ma60),
        "above_ma20": bool(ma20 and close >= ma20),
        "above_ma60": bool(ma60 and close >= ma60),
    }


def find_recent_large_candle(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(rows) < 3:
        return None

    recent = rows[-6:-1]
    for offset, row in enumerate(reversed(recent), start=1):
        pct_chg = float(row.get("pct_chg", 0) or 0)
        open_price = float(row.get("open", 0) or 0)
        close_price = float(row.get("close", 0) or 0)
        high = float(row.get("high", 0) or 0)
        low = float(row.get("low", 0) or 0)
        if pct_chg >= 7.0 and close_price > open_price:
            return {
                "date": row.get("date"),
                "days_ago": offset,
                "high": round(high, 2),
                "low": round(low, 2),
                "midpoint": round((open_price + close_price) / 2, 2),
                "pct_chg": round(pct_chg, 2),
            }
    return None
