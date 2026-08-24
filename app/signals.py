from __future__ import annotations

from typing import Any


ACTION_BY_SIGNAL = {
    "买入": "满足 MA5/MA10 买入条件，可按计划执行",
    "减仓": "先减 1/2，等待 MA5 重新转强",
    "剔除": "清仓或移出候选，等待重新站回 MA10",
    "观察": "条件尚未完整满足，继续观察",
}


def evaluate_signal(stock: dict[str, Any]) -> dict[str, Any]:
    """按价格、MA5/MA10 及其斜率生成个股操作信号。"""
    quote = stock.get("quote") or {}
    ind = stock.get("indicators") or {}
    price = quote.get("price") or stock.get("price") or stock.get("close")
    ma5 = ind.get("ma5")
    ma10 = ind.get("ma10")
    ma5_slope = ind.get("ma5_slope")
    ma10_slope = ind.get("ma10_slope")

    missing = [
        label
        for label, value in (
            ("现价", price),
            ("MA5", ma5),
            ("MA10", ma10),
            ("MA5斜率", ma5_slope),
            ("MA10斜率", ma10_slope),
        )
        if value is None
    ]
    if missing:
        reason = f"缺少{'、'.join(missing)}数据，暂不生成操作信号"
        return make_signal("观察", "数据待补全", [reason], ["等待日K数据补全"], "中", reason)

    # 风险信号优先，避免同时满足减仓条件时被较弱信号覆盖。
    exit_reasons: list[str] = []
    exit_details: list[str] = []
    if price < ma10:
        exit_reasons.append("当前价跌破 MA10")
        exit_details.append(f"现价 {price:.2f} < MA10 {ma10:.2f}")
    if ma5_slope < 0 and ma10_slope < 0:
        exit_reasons.append("MA5 与 MA10 斜率同时为负")
        exit_details.append(f"MA5斜率 {ma5_slope:+.2f}% < 0，MA10斜率 {ma10_slope:+.2f}% < 0")
    if exit_reasons:
        return make_signal(
            "剔除",
            "清仓 / 剔除",
            exit_reasons,
            ["重新站回 MA10，且 MA5/MA10 斜率修复后再观察"],
            "高",
            "；".join(exit_details),
        )

    reduce_reasons: list[str] = []
    reduce_details: list[str] = []
    if price < ma5:
        reduce_reasons.append("当前价跌破 MA5")
        reduce_details.append(f"现价 {price:.2f} < MA5 {ma5:.2f}")
    if ma5_slope <= 0:
        reduce_reasons.append("MA5 斜率走平或转负")
        reduce_details.append(f"MA5斜率 {ma5_slope:+.2f}% ≤ 0")
    if reduce_reasons:
        return make_signal(
            "减仓",
            "短线转弱",
            reduce_reasons,
            ["先减 1/2；现价重新站上 MA5 且双均线斜率向上后再评估"],
            "中高",
            "；".join(reduce_details),
        )

    if price > ma5 and ma5_slope > 0 and ma10_slope > 0 and ma5 > ma10:
        reasons = ["当前价站上 MA5", "MA5 斜率向上", "MA10 斜率向上", "MA5 位于 MA10 上方"]
        detail = (
            f"现价 {price:.2f} > MA5 {ma5:.2f}；"
            f"MA5斜率 {ma5_slope:+.2f}% > 0；"
            f"MA10斜率 {ma10_slope:+.2f}% > 0；"
            f"MA5 {ma5:.2f} > MA10 {ma10:.2f}"
        )
        return make_signal("买入", "MA5/MA10 转强", reasons, ["跌破 MA5 或 MA5 斜率走平时减仓"], "中", detail)

    unmet: list[str] = []
    if price <= ma5:
        unmet.append(f"现价 {price:.2f} 未站上 MA5 {ma5:.2f}")
    if ma5_slope <= 0:
        unmet.append(f"MA5斜率 {ma5_slope:+.2f}% 未大于 0")
    if ma10_slope <= 0:
        unmet.append(f"MA10斜率 {ma10_slope:+.2f}% 未大于 0")
    if ma5 <= ma10:
        unmet.append(f"MA5 {ma5:.2f} 未站上 MA10 {ma10:.2f}")
    return make_signal(
        "观察",
        "等待确认",
        ["买入条件尚未全部满足"],
        ["等待现价站上 MA5、双均线斜率向上且 MA5 > MA10"],
        "中",
        "；".join(unmet),
    )


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
        "rank_score": rank_score(signal),
    }


def rank_score(signal: str) -> int:
    return {
        "买入": 100,
        "观察": 50,
        "减仓": 25,
        "剔除": 5,
    }.get(signal, 0)
