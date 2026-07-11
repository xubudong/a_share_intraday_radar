from app.indicators import compute_indicators


def make_rows(closes):
    return [
        {
            "date": f"2026-01-{index + 1:02d}",
            "open": close,
            "close": close,
            "high": close,
            "low": close,
            "volume": 100,
        }
        for index, close in enumerate(closes)
    ]


def test_compute_indicators_reports_5_and_20_day_returns():
    closes = [100.0] * 21
    closes[-6] = 110.0
    closes[-1] = 121.0

    indicators = compute_indicators(make_rows(closes))

    assert indicators["return_5d"] == 10.0
    assert indicators["return_20d"] == 21.0


def test_period_returns_require_enough_history():
    indicators = compute_indicators(make_rows([100.0] * 5))

    assert indicators["return_5d"] is None
    assert indicators["return_20d"] is None


def test_compute_indicators_reports_ma_slopes():
    closes = [10, 10, 10, 10, 10, 11, 11, 11, 11, 11, 12]

    indicators = compute_indicators(make_rows(closes))

    assert indicators["ma5_slope"] == 1.82
    assert indicators["ma10_slope"] == 1.9


def test_ma_slopes_require_previous_ma():
    indicators = compute_indicators(make_rows([10.0] * 10))

    assert indicators["ma5_slope"] == 0.0
    assert indicators["ma10_slope"] is None
