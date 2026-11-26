import math
import pytest

from app.services.market_context_dummy_api import DummyMarketContextAPI
from app.services.market_regime_context import MarketRegimeContextEngine


def candle(o, h, l, c, volume=100):
    return {"open": o, "high": h, "low": l, "close": c, "volume": volume}


def flat_series(n=120, base=100.0, width_pct=0.2):
    return [candle(base, base*(1+width_pct/100), base*(1-width_pct/100), base) for _ in range(n)]


def trending_series(direction=1, n=120):
    closes=[100.0]
    for i in range(n-1):
        closes.append(closes[-1]*(1+direction*0.003))
    return [candle(closes[i-1] if i else closes[i], max(closes[i-1] if i else closes[i],closes[i]) * 1.001,
                   min(closes[i-1] if i else closes[i],closes[i]) * 0.999, closes[i]) for i in range(n)]


def regime_engine():
    return MarketRegimeContextEngine()


def test_dummy_provider_is_explicit_and_not_live():
    data=DummyMarketContextAPI().get_candles("BTCUSDT","1m",120)
    assert data["data_mode"]=="DUMMY"
    assert data["is_live"] is False
    assert data["provider"]=="dummy_ohlcv_api"
    assert len(data["candles"])==120
    assert data["note"].startswith("Mock OHLCV")


@pytest.mark.parametrize("symbol,interval", [("BTCUSDT","1m"),("ETHUSDT","5m"),("SOLUSDT","1h")])
def test_dummy_provider_candle_shape(symbol,interval):
    data=DummyMarketContextAPI().get_candles(symbol,interval,80)
    assert data["symbol"]==symbol
    assert data["interval"]==interval
    for row in data["candles"]:
        assert set(row)=={"timestamp_ms","open","high","low","close","volume"}
        assert row["high"]>=max(row["open"],row["close"])
        assert row["low"]<=min(row["open"],row["close"])
        assert row["volume"]>=0


def test_engine_outputs_complete_schema_and_heuristic_disclaimers():
    result=regime_engine().analyze(DummyMarketContextAPI().get_candles("ETHUSDT","5m",120))
    assert result["engine"]=="phase9_market_regime_context"
    assert result["data_mode"]=="DUMMY" and result["is_live"] is False
    assert result["candle_count"]==120
    assert set(result["classification"])=={"market_regime","trend","volatility_state","volatility_spike"}
    assert result["classification"]["trend"] in {"UPTREND","DOWNTREND","RANGING"}
    assert result["classification"]["volatility_state"] in {"EXPANSION","COMPRESSION","NORMAL"}
    assert result["classification"]["market_regime"] in {"TRENDING_VOLATILE","TRENDING_LOW_VOL","RANGE_VOLATILE","RANGE_COMPRESSION","MIXED_OR_NORMAL"}
    assert any("heuristic" in d.lower() for d in result["diagnostics"])
    assert any("not live" in d.lower() for d in result["diagnostics"])


@pytest.mark.parametrize("direction,expected", [(1,"UPTREND"),(-1,"DOWNTREND")])
def test_trend_classification_responds_to_price_progress(direction,expected):
    result=regime_engine().analyze({"candles":trending_series(direction)})
    assert result["classification"]["trend"]==expected


def test_flat_price_series_classifies_as_range():
    result=regime_engine().analyze({"candles":flat_series()})
    assert result["classification"]["trend"]=="RANGING"


def test_volatile_range_classifies_range_expansion():
    rows=flat_series(120,width_pct=0.2)
    # Alternating closes create recent return volatility without directional drift.
    for i in range(80,120):
        close=100*(1+(0.01 if i%2 else -0.01))
        rows[i]=candle(100,close*1.02,close*0.98,close)
    result=regime_engine().analyze({"candles":rows})
    assert result["classification"]["volatility_state"]=="EXPANSION"


def test_low_volatility_range_compression():
    rows=[]
    for i in range(120):
        close=100*(1+(0.00005 if i%2 else -0.00005))
        rows.append(candle(100,close*1.0001,close*0.9999,close))
    result=regime_engine().analyze({"candles":rows})
    assert result["classification"]["volatility_state"]=="COMPRESSION"


def test_normal_volatility_state_possible():
    rows=[]
    for i in range(120):
        close=100*(1+(0.001 if i%2 else -0.001))
        rows.append(candle(100,close*1.002,close*0.998,close))
    result=regime_engine().analyze({"candles":rows})
    assert result["classification"]["volatility_state"] in {"NORMAL","EXPANSION","COMPRESSION"}


def test_volatility_spike_flag_detects_extreme_last_candle():
    rows=flat_series(120,width_pct=0.1)
    rows[-1]=candle(100,110,90,100)
    result=regime_engine().analyze({"candles":rows})
    assert result["classification"]["volatility_spike"]=="TRUE"


def test_spike_flag_is_false_for_regular_candles():
    result=regime_engine().analyze({"candles":flat_series(120,width_pct=0.2)})
    assert result["classification"]["volatility_spike"]=="FALSE"


@pytest.mark.parametrize("invalid",[
    None, {}, [], "not-candle", {"open":100,"high":99,"low":101,"close":100,"volume":1},
    {"open":0,"high":1,"low":0.5,"close":0.8,"volume":1},
    {"open":100,"high":float("nan"),"low":99,"close":100,"volume":1},
    {"open":100,"high":float("inf"),"low":99,"close":100,"volume":1},
])
def test_invalid_candles_are_skipped(invalid):
    rows=flat_series(120)
    rows[0]=invalid
    result=regime_engine().analyze({"candles":rows})
    assert result["candle_count"]==119


def test_zero_negative_and_invalid_volume_are_sanitized_to_zero():
    rows=flat_series(120)
    rows[0]["volume"]=-3
    rows[1]["volume"]="invalid"
    rows[2]["volume"]=None
    result=regime_engine().analyze({"candles":rows})
    assert result["candle_count"]==120


def test_rejects_insufficient_valid_candles():
    with pytest.raises(ValueError,match="At least 40 valid candles"):
        regime_engine().analyze({"candles":flat_series(39)})


def test_rejects_insufficient_after_invalid_candles_removed():
    rows=flat_series(60)
    rows[:25]=[None]*25
    with pytest.raises(ValueError,match="At least 40 valid candles"):
        regime_engine().analyze({"candles":rows})


def test_non_dict_payload_is_rejected_cleanly_with_value_error():
    with pytest.raises((AttributeError,ValueError,TypeError)):
        regime_engine().analyze(None)


@pytest.mark.parametrize("fast,slow",[(3,4),(12,36),(50,200),(0,1),(-1,-2),(100,400)])
def test_periods_are_bounded_and_valid(fast,slow):
    result=regime_engine().analyze({"candles":flat_series(240)},fast,slow)
    assert result["candle_count"]==240
    assert math.isfinite(result["metrics"]["fast_vs_slow_pct"])


@pytest.mark.parametrize("fast,slow",[(None,None),("bad","bad"),("NaN","Infinity"),(float("nan"),float("inf"))])
def test_malformed_periods_use_safe_defaults(fast,slow):
    result=regime_engine().analyze({"candles":flat_series(120)},fast,slow)
    assert result["candle_count"]==120


def test_history_limit_clamped_to_range_and_uses_recent_tail():
    engine=MarketRegimeContextEngine(history_limit=60)
    rows=flat_series(120)
    result=engine.analyze({"candles":rows})
    assert result["candle_count"]==60


@pytest.mark.parametrize("limit,expected",[(1,60),(60,60),(500,500),(5000,1000),(-10,60)])
def test_constructor_history_limit_clamped(limit,expected):
    assert MarketRegimeContextEngine(limit).history_limit==expected


def test_metrics_are_finite_or_nullable_and_bounded():
    result=regime_engine().analyze({"candles":flat_series(120)})
    metrics=result["metrics"]
    for key in ("fast_average_close","slow_average_close","fast_vs_slow_pct",
                 "recent_return_volatility_pct","baseline_return_volatility_pct",
                 "recent_average_range_pct","baseline_average_range_pct","latest_candle_range_pct"):
        assert math.isfinite(metrics[key])
    assert metrics["volatility_ratio"] is None or math.isfinite(metrics["volatility_ratio"])
    assert metrics["range_ratio"] is None or math.isfinite(metrics["range_ratio"])

# Integration coverage for Layer 7 as currently represented inside the nine-layer
# decision engine (scanner 24-hour trend/range proxy, distinct from the candle
# classifier endpoint).
from app.services.nine_layer_decision_engine import NineLayerDecisionEngine


def decision_engine_l7(market):
    return NineLayerDecisionEngine().evaluate("BTCUSDT", {"market":market}, risk={"allowed":True,"blockers":[]})


def l7(result):
    return result["layers"]["volatility_regime"]


@pytest.mark.parametrize("change,expected",[(10,"BUY"),(-10,"SELL"),(0,"NEUTRAL"),(7.4,"NEUTRAL")])
def test_nine_layer_l7_direction_from_24h_price_change_proxy(change,expected):
    result=decision_engine_l7({"range_24h_pct":5.0,"price_change_24h_pct":change})
    assert l7(result)["available"] is True
    assert l7(result)["direction"]==expected


def test_nine_layer_l7_proxy_score_is_bounded():
    result=decision_engine_l7({"range_24h_pct":100.0,"price_change_24h_pct":9999})
    assert l7(result)["score"]==50


@pytest.mark.parametrize("market",[
    {}, {"range_24h_pct":2.0}, {"price_change_24h_pct":1.0},
    {"range_24h_pct":None,"price_change_24h_pct":2.0},
    {"range_24h_pct":2.0,"price_change_24h_pct":"invalid"},
    {"range_24h_pct":2.0,"price_change_24h_pct":float("nan")},
    {"range_24h_pct":2.0,"price_change_24h_pct":float("inf")},
])
def test_nine_layer_l7_proxy_missing_or_invalid_data_unavailable(market):
    result=decision_engine_l7(market)
    assert l7(result)["available"] is False
    assert l7(result)["score"] is None
