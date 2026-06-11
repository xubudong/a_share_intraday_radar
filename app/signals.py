from __future__ import annotations

from typing import Any


ACTION_BY_SIGNAL = {
    "可试仓": "缩量回踩企稳，可按计划仓位的 30%-50% 试仓",
    "等回踩": "强势但位置偏高，等待 MA5/MA10 或大阳线半分位",
    "突破观察": "平台突破或接近突破，次日不破突破位再确认",
    "二次确认": "大阳线后横住，再放量转强可小仓跟踪",
    "过热不追": "短线过热，避免追高，等缩量回落",
    "走弱剔除": "趋势破坏，先移出买入候选",
    "观察": "未出现清晰买点，继续观察",
}


def uptrend_detail(ind: dict[str, Any], price: float | None, negated: bool = False) -> str:
    """Build a detail string explaining the uptrend condition:
    close > MA20 AND MA5 > MA10 > MA20 > MA60."""
    label = "非多头排列" if negated else "多头排列✓"
    cond = "收盘>MA20且MA5>MA10>MA20>MA60"
    return f"{label}（{cond}）"


def evaluate_signal(stock: dict[str, Any]) -> dict[str, Any]:
    quote = stock.get("quote") or {}
    ind = stock.get("indicators") or {}
    price = quote.get("price") or stock.get("close")
    pct_chg = quote.get("pct_chg") or 0
    volume_ratio = ind.get("volume_ratio")
    rsi14 = ind.get("rsi14")
    dev_ma5 = ind.get("dev_ma5")
    dev_ma10 = ind.get("dev_ma10")
    dev_ma20 = ind.get("dev_ma20")
    from_high20 = ind.get("from_high20")
    high20_prev = ind.get("high20_prev")
    high60_prev = ind.get("high60_prev")

    reasons: list[str] = []
    next_trigger: list[str] = []
    detail: str = ""
    risk = "中"

    weak = (
        (ind.get("ma60") and price and price < ind["ma60"])
        or (ind.get("ma20") and price and price < ind["ma20"] and pct_chg <= -3 and (volume_ratio or 0) >= 1.2)
    )
    if weak:
        reasons.append("跌破关键均线或放量下跌，趋势买点失效")
        if ind.get("ma60") and price and price < ind["ma60"]:
            detail = f"现价 {price:.2f} < MA60 {ind['ma60']:.2f}"
        elif ind.get("ma20") and price and price < ind["ma20"]:
            parts = [f"现价 {price:.2f} < MA20 {ind['ma20']:.2f}"]
            parts.append(f"跌幅 {pct_chg:.1f}%≤-3%")
            if volume_ratio is not None:
                parts.append(f"量比 {volume_ratio:.2f}≥1.2")
            detail = "，".join(parts)
        return make_signal("走弱剔除", "趋势防守", reasons, ["重新站回 MA20 且量能修复"], "高", detail)

    overheat = (
        pct_chg >= 8
        or (rsi14 is not None and rsi14 >= 78)
        or (dev_ma5 is not None and dev_ma5 >= 5)
        or (dev_ma20 is not None and dev_ma20 >= 14)
    )

    uptrend = bool(ind.get("uptrend"))
    near_ma10_or_ma20 = (
        (dev_ma10 is not None and -2.5 <= dev_ma10 <= 2.5)
        or (dev_ma20 is not None and -1.5 <= dev_ma20 <= 4.0)
    )
    pullback_depth_ok = from_high20 is not None and -10 <= from_high20 <= -3
    volume_calm = volume_ratio is None or volume_ratio <= 1.25

    if uptrend and pullback_depth_ok and near_ma10_or_ma20 and volume_calm and not overheat:
        reasons.extend(["多头排列仍在", "从 20 日高点回撤 3%-10%", "靠近 MA10/MA20 且量能收敛"])
        parts = [f"回撤 {from_high20:.1f}%∈[-10%,-3%]"]
        if dev_ma10 is not None and -2.5 <= dev_ma10 <= 2.5:
            parts.append(f"距MA10 {dev_ma10:+.1f}%∈[-2.5%,2.5%]")
        if dev_ma20 is not None and -1.5 <= dev_ma20 <= 4.0:
            parts.append(f"距MA20 {dev_ma20:+.1f}%∈[-1.5%,4.0%]")
        if volume_ratio is not None:
            parts.append(f"量比 {volume_ratio:.2f}≤1.25")
        parts.append(uptrend_detail(ind, price))
        detail = "，".join(parts)
        stop = ind.get("ma20") or ind.get("low20")
        if stop:
            next_trigger.append(f"跌破 MA20 附近 {stop:.2f} 元减仓或止损")
        return make_signal("可试仓", "回踩买点", reasons, next_trigger, "中", detail)

    large = ind.get("large_candle")
    if large and price:
        held_midpoint = price >= large["midpoint"]
        retest_high = price >= large["high"] * 0.985
        if held_midpoint and retest_high and not overheat:
            reasons.extend([f"{large['date']} 大阳线后未破实体半分位", "价格重新接近大阳线高点"])
            detail = (
                f"{large['date']} 涨 {large['pct_chg']:.1f}%≥7%（大阳线），"
                f"半分位 {large['midpoint']:.2f}，"
                f"现价 {price:.2f}≥半分位✓，"
                f"最高 {large['high']:.2f}，"
                f"现价 {price:.2f}≥{large['high'] * 0.985:.2f}（最高×98.5%）✓"
            )
            next_trigger.append(f"放量站上 {large['high']:.2f} 元后确认")
            return make_signal("二次确认", "二次买点", reasons, next_trigger, "中高", detail)

    breakout_level = max([x for x in [high20_prev, high60_prev] if x is not None], default=None)
    breakout = (
        breakout_level is not None
        and price is not None
        and price >= breakout_level * 0.995
        and (volume_ratio or 0) >= 1.35
        and 1 <= pct_chg <= 8
    )
    if breakout and not overheat:
        reasons.extend(["接近或突破 20/60 日平台高点", "量能较 20 日均量明显放大", "涨幅未进入过热区"])
        level_label = "60日高" if high60_prev and breakout_level == high60_prev else "20日高"
        parts = [f"突破{level_label} {breakout_level:.2f}"]
        parts.append(f"现价 {price:.2f}≥{breakout_level * 0.995:.2f}（突破位×99.5%）✓")
        parts.append(f"涨幅 {pct_chg:.1f}%∈[1%,8%)✓")
        if volume_ratio is not None:
            parts.append(f"量比 {volume_ratio:.2f}≥1.35✓")
        detail = "，".join(parts)
        next_trigger.append(f"次日不跌回 {breakout_level:.2f} 元下方再确认")
        return make_signal("突破观察", "平台突破", reasons, next_trigger, "中高", detail)

    if overheat:
        reasons.append("涨幅、RSI 或均线乖离进入短线过热区")
        if dev_ma5 is not None:
            reasons.append(f"距离 MA5 约 {dev_ma5:.1f}%")
        parts = []
        if pct_chg >= 8:
            parts.append(f"日涨 {pct_chg:.1f}%≥8%")
        if rsi14 is not None and rsi14 >= 78:
            parts.append(f"RSI {rsi14:.0f}≥78")
        if dev_ma5 is not None and dev_ma5 >= 5:
            parts.append(f"乖MA5 {dev_ma5:+.1f}%≥5%")
        if dev_ma20 is not None and dev_ma20 >= 14:
            parts.append(f"乖MA20 {dev_ma20:+.1f}%≥14%")
        detail = "，".join(parts) if parts else "短线过热"
        next_trigger.append("等待缩量回踩 MA5/MA10，或大阳线半分位不破后的二次确认")
        return make_signal("过热不追", "位置风控", reasons, next_trigger, "高", detail)

    if uptrend:
        reasons.append("趋势仍强，但还没有缩量回踩或放量突破的清晰触发")
        parts = [uptrend_detail(ind, price)]
        if from_high20 is not None:
            parts.append(f"回撤 {from_high20:.1f}%∉[-10%,-3%]")
        if dev_ma20 is not None:
            parts.append(f"距MA20 {dev_ma20:+.1f}%∉[-1.5%,4.0%]")
        if volume_ratio is not None and volume_ratio > 1.25:
            parts.append(f"量比 {volume_ratio:.2f}>1.25（未缩量）")
        detail = "，".join(parts)
        next_trigger.append("回撤 3%-8% 且靠近 MA10/MA20 时转入可试仓")
        return make_signal("等回踩", "趋势等待", reasons, next_trigger, risk, detail)

    reasons.append("趋势结构尚未满足买点条件")
    parts = [uptrend_detail(ind, price, negated=True)]
    if dev_ma20 is not None:
        parts.append(f"距MA20 {dev_ma20:+.1f}%")
    if from_high20 is not None:
        parts.append(f"回撤 {from_high20:.1f}%")
    detail = "，".join(parts)
    next_trigger.append("先站上 MA20，并观察量能是否同步修复")
    return make_signal("观察", "等待确认", reasons, next_trigger, "中", detail)


def make_signal(
    signal: str,
    setup: str,
    reasons: list[str],
    next_trigger: list[str],
    risk: str,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "signal": signal,
        "setup": setup,
        "action": ACTION_BY_SIGNAL[signal],
        "reasons": reasons,
        "next_trigger": next_trigger,
        "risk": risk,
        "detail": detail,
        "rank_score": rank_score(signal, risk),
    }


def rank_score(signal: str, risk: str) -> int:
    base = {
        "可试仓": 95,
        "二次确认": 85,
        "突破观察": 80,
        "等回踩": 60,
        "观察": 40,
        "过热不追": 30,
        "走弱剔除": 5,
    }.get(signal, 0)
    if risk == "高":
        base -= 5
    return base
