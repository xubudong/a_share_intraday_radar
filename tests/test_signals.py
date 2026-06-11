from app.signals import evaluate_signal


def stock(price=100, pct_chg=2, indicators=None):
    return {
        "price": price,
        "quote": {"price": price, "pct_chg": pct_chg},
        "indicators": indicators or {},
    }


def test_pullback_signal_is_actionable():
    result = evaluate_signal(
        stock(
            indicators={
                "ma5": 101,
                "ma10": 100,
                "ma20": 98,
                "ma60": 90,
                "dev_ma10": 0.2,
                "dev_ma20": 2.0,
                "dev_ma5": -0.8,
                "from_high20": -5.0,
                "volume_ratio": 0.8,
                "rsi14": 55,
                "uptrend": True,
            }
        )
    )

    assert result["signal"] == "可试仓"
    assert result["setup"] == "回踩买点"


def test_overheat_signal_blocks_chasing():
    result = evaluate_signal(
        stock(
            price=120,
            pct_chg=9.5,
            indicators={
                "ma5": 110,
                "ma20": 98,
                "dev_ma5": 9.0,
                "dev_ma20": 22.4,
                "rsi14": 82,
                "uptrend": True,
            },
        )
    )

    assert result["signal"] == "过热不追"


def test_weak_signal_takes_priority():
    result = evaluate_signal(
        stock(
            price=88,
            pct_chg=-4,
            indicators={
                "ma20": 96,
                "ma60": 90,
                "volume_ratio": 1.5,
                "rsi14": 35,
            },
        )
    )

    assert result["signal"] == "走弱剔除"


def test_breakout_signal():
    result = evaluate_signal(
        stock(
            price=101,
            pct_chg=4,
            indicators={
                "ma5": 99,
                "ma20": 92,
                "ma60": 86,
                "dev_ma5": 2.0,
                "dev_ma20": 9.8,
                "rsi14": 65,
                "volume_ratio": 1.8,
                "high20_prev": 100,
                "high60_prev": 100,
                "uptrend": True,
            },
        )
    )

    assert result["signal"] == "突破观察"


def test_second_confirmation_signal():
    result = evaluate_signal(
        stock(
            price=105,
            pct_chg=2,
            indicators={
                "ma5": 103,
                "ma20": 94,
                "dev_ma5": 1.9,
                "dev_ma20": 11.7,
                "rsi14": 66,
                "large_candle": {
                    "date": "2026-06-09",
                    "days_ago": 2,
                    "high": 106,
                    "midpoint": 98,
                    "pct_chg": 9,
                },
            },
        )
    )

    assert result["signal"] == "二次确认"
