from app.services.market_context_dummy_api import DummyMarketContextAPI
from app.services.market_regime_context import MarketRegimeContextEngine

def test_dummy_provider_explicitly_not_live():
    data=DummyMarketContextAPI().get_candles("BTCUSDT","1m",120)
    assert data["data_mode"]=="DUMMY" and data["is_live"] is False
    assert len(data["candles"])==120

def test_engine_returns_regime_classification():
    data=DummyMarketContextAPI().get_candles("ETHUSDT","5m",120)
    result=MarketRegimeContextEngine().analyze(data)
    assert result["data_mode"]=="DUMMY" and result["is_live"] is False
    assert result["classification"]["market_regime"] in {"TRENDING_VOLATILE","TRENDING_LOW_VOL","RANGE_VOLATILE","RANGE_COMPRESSION","MIXED_OR_NORMAL"}

def test_rejects_short_series():
    try: MarketRegimeContextEngine().analyze({"candles":[]})
    except ValueError as exc: assert "40 valid candles" in str(exc)
    else: raise AssertionError("Expected insufficient-data ValueError")
