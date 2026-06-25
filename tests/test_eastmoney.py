from app import eastmoney


def test_market_indices_focus_on_sci_tech_and_external_markets():
    codes = [index["code"] for index in eastmoney.MARKET_INDICES]
    names = [index["name"] for index in eastmoney.MARKET_INDICES]

    assert codes == ["000001", "000688", "399006", "N225", "KS11", "NDX"]
    assert "科创50" in names
    assert "日经225" in names
    assert "韩国KOSPI" in names
    assert "昨夜纳指" in names
    assert "深证成指" not in names


def test_market_index_code_keeps_external_symbols():
    assert eastmoney.normalize_market_index_code("1") == "000001"
    assert eastmoney.normalize_market_index_code("N225") == "N225"


def test_eastmoney_market_index_quote_chunk_keeps_alpha_codes(monkeypatch):
    monkeypatch.setattr(
        eastmoney,
        "request_json",
        lambda *args, **kwargs: {
            "data": {
                "diff": [
                    {
                        "f2": 71854.88,
                        "f3": 3.87,
                        "f4": 2679.91,
                        "f12": "N225",
                        "f14": "日经225",
                        "f15": 71886.94,
                        "f16": 69982.67,
                        "f17": 70114.09,
                        "f18": 69174.97,
                    }
                ]
            }
        },
    )

    quotes = eastmoney.fetch_eastmoney_market_index_quote_chunk(
        [{"code": "N225", "name": "日经225", "secid": "100.N225"}]
    )

    assert quotes["N225"]["price"] == 71854.88
    assert quotes["N225"]["prev_close"] == 69174.97


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


def test_market_indices_fall_back_to_tencent(monkeypatch):
    monkeypatch.setattr(
        eastmoney,
        "fetch_eastmoney_market_index_quotes",
        lambda: (_ for _ in ()).throw(OSError("eastmoney unavailable")),
    )
    monkeypatch.setattr(
        eastmoney,
        "fetch_tencent_market_index_quotes",
        lambda indices=None: {
            "000001": {
                "code": "000001",
                "name": "上证指数",
                "price": 4098.85,
                "pct_chg": 0.06,
                "change": 2.38,
                "source": "tencent_index",
            }
        },
    )
    monkeypatch.setattr(
        eastmoney,
        "fetch_market_index_intraday",
        lambda index: [4094.21, 4099.22, 4098.85],
    )

    indices = eastmoney.fetch_market_indices()

    assert indices == [
        {
            "code": "000001",
            "symbol": "sh000001",
            "name": "上证指数",
            "price": 4098.85,
            "pct_chg": 0.06,
            "change": 2.38,
            "source": "tencent_index",
            "intraday": [4094.21, 4099.22, 4098.85],
        }
    ]


def test_parse_sina_intraday_uses_latest_trading_date(monkeypatch):
    payload = (
        b'{"result":{"data":['
        b'{"day":"2026-06-12 15:00:00","close":"10.00"},'
        b'{"day":"2026-06-15 09:31:00","close":"10.20"},'
        b'{"day":"2026-06-15 09:32:00","close":"10.30"}]}}'
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

    assert eastmoney.fetch_sina_intraday_trends("300408") == [10.2, 10.3]
