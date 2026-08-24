from app.signals import evaluate_signal


def stock(price=100, indicators=None):
    return {
        "price": price,
        "quote": {"price": price},
        "indicators": indicators or {},
    }


def test_buy_requires_all_ma5_ma10_conditions():
    result = evaluate_signal(
        stock(
            price=101,
            indicators={
                "ma5": 100,
                "ma10": 99,
                "ma5_slope": 0.8,
                "ma10_slope": 0.3,
            },
        )
    )

    assert result["signal"] == "买入"
    assert "现价 101.00 > MA5 100.00" in result["detail"]
    assert len(result["reasons"]) == 4


def test_reduce_when_price_falls_below_ma5():
    result = evaluate_signal(
        stock(
            price=99.5,
            indicators={
                "ma5": 100,
                "ma10": 99,
                "ma5_slope": 0.2,
                "ma10_slope": 0.1,
            },
        )
    )

    assert result["signal"] == "减仓"
    assert result["action"].startswith("先减 1/2")
    assert "现价 99.50 < MA5 100.00" in result["detail"]


def test_reduce_when_ma5_slope_is_flat():
    result = evaluate_signal(
        stock(
            price=101,
            indicators={
                "ma5": 100,
                "ma10": 99,
                "ma5_slope": 0,
                "ma10_slope": 0.1,
            },
        )
    )

    assert result["signal"] == "减仓"
    assert "MA5斜率 +0.00% ≤ 0" in result["detail"]


def test_exit_takes_priority_when_price_falls_below_ma10():
    result = evaluate_signal(
        stock(
            price=98,
            indicators={
                "ma5": 100,
                "ma10": 99,
                "ma5_slope": 0.2,
                "ma10_slope": 0.1,
            },
        )
    )

    assert result["signal"] == "剔除"
    assert "现价 98.00 < MA10 99.00" in result["detail"]


def test_exit_when_both_slopes_are_negative():
    result = evaluate_signal(
        stock(
            price=102,
            indicators={
                "ma5": 101,
                "ma10": 100,
                "ma5_slope": -0.2,
                "ma10_slope": -0.1,
            },
        )
    )

    assert result["signal"] == "剔除"
    assert "MA5 与 MA10 斜率同时为负" in result["reasons"]


def test_observe_when_buy_conditions_are_incomplete():
    result = evaluate_signal(
        stock(
            price=103,
            indicators={
                "ma5": 100,
                "ma10": 101,
                "ma5_slope": 0.3,
                "ma10_slope": 0.2,
            },
        )
    )

    assert result["signal"] == "观察"
    assert "MA5 100.00 未站上 MA10 101.00" in result["detail"]


def test_observe_when_ma_data_is_missing():
    result = evaluate_signal(stock(price=100, indicators={"ma5": 99}))

    assert result["signal"] == "观察"
    assert "缺少MA10、MA5斜率、MA10斜率数据" in result["detail"]
