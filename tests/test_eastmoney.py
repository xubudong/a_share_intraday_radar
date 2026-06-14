from app import eastmoney


def test_parse_tencent_quote_maps_realtime_fields():
    fields = [""] * 86
    fields[1] = "测试股份"
    fields[2] = "600001"
    fields[3] = "12.34"
    fields[4] = "12.00"
    fields[5] = "12.10"
    fields[30] = "20260611150000"
    fields[31] = "0.34"
    fields[32] = "2.83"
    fields[33] = "12.50"
    fields[34] = "11.90"
    fields[35] = "12.34/1000/1234000"
    fields[36] = "1000"
    fields[45] = "88.50"

    quote = eastmoney.parse_tencent_quote('v_sh600001="' + "~".join(fields) + '";')

    assert quote is not None
    assert quote["code"] == "600001"
    assert quote["price"] == 12.34
    assert quote["pct_chg"] == 2.83
    assert quote["amount"] == 1234000
    assert quote["turnover_market_cap"] == 8850000000
    assert quote["source"] == "tencent_realtime"


def test_realtime_quotes_fall_back_to_tencent(monkeypatch):
    monkeypatch.setattr(
        eastmoney,
        "request_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("eastmoney unavailable")),
    )
    monkeypatch.setattr(eastmoney.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        eastmoney,
        "fetch_tencent_realtime_quotes",
        lambda codes: {
            code: {
                "code": code,
                "price": 10.0,
                "pct_chg": 1.0,
                "source": "tencent_realtime",
            }
            for code in codes
        },
    )

    quotes = eastmoney.fetch_realtime_quotes(["600001", "000001"])

    assert set(quotes) == {"600001", "000001"}
    assert all(quote["source"] == "tencent_realtime" for quote in quotes.values())


def test_parse_tencent_intraday_prices(monkeypatch):
    payload = (
        b'{"code":0,"data":{"sz300408":{"data":{"data":'
        b'["0930 136.38 10 1000.00","0931 134.78 20 2000.00"]}}}}'
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return payload

    monkeypatch.setattr(
        eastmoney.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    assert eastmoney.fetch_tencent_intraday_trends("300408") == [136.38, 134.78]


def test_intraday_trends_fall_back_to_tencent(monkeypatch):
    monkeypatch.setattr(eastmoney, "request_json", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        eastmoney,
        "fetch_tencent_intraday_trends",
        lambda code: [10.0, 10.2, 10.1],
    )

    assert eastmoney.fetch_intraday_trends("300408") == [10.0, 10.2, 10.1]
