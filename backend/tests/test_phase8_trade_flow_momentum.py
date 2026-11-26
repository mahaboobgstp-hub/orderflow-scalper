import time
import pytest
from app.services.trade_flow_momentum import TradeFlowMomentumDetector

def book(mid=100):
    return {"exchange":"bybit","symbol":"BTCUSDT","bids":[[mid-.01,5],[mid-.02,3]],"asks":[[mid+.01,4],[mid+.02,2]],
        "synchronized":True,"stale":False,"age_seconds":.1,"integrity_error":None}
def tape(sides,prices=None):
    now=int(time.time()*1000); prices=prices or [100.0]*len(sides)
    return [{"side":s,"price":p,"quantity":1.0,"received_timestamp_ms":now-i*100} for i,(s,p) in enumerate(zip(sides,prices))]
def test_buy_dominance():
    result=TradeFlowMomentumDetector().analyze(book(),tape(["buy"]*10),15)
    assert result["flow_classification"]=="BUY_DOMINANT"
    assert result["metrics"]["net_delta"]==10
def test_sell_dominance():
    result=TradeFlowMomentumDetector().analyze(book(),tape(["sell"]*10),15)
    assert result["flow_classification"]=="SELL_DOMINANT"
def test_balanced_flow():
    result=TradeFlowMomentumDetector().analyze(book(),tape(["buy","sell"]*5),15)
    assert result["flow_classification"]=="BALANCED"
def test_insufficient_data():
    result=TradeFlowMomentumDetector().analyze(book(),tape(["buy"]*3),15)
    assert result["flow_classification"]=="INSUFFICIENT_DATA"
def test_buy_flow_without_price_progress():
    result=TradeFlowMomentumDetector().analyze(book(99.9),tape(["buy"]*10,[100]*10),15)
    assert result["divergence"]=="BUY_FLOW_WITHOUT_UPWARD_PROGRESS"
def test_reject_bad_book():
    bad=book();bad["synchronized"]=False
    with pytest.raises(ValueError): TradeFlowMomentumDetector().analyze(bad,[],15)
    bad=book();bad["stale"]=True
    with pytest.raises(ValueError): TradeFlowMomentumDetector().analyze(bad,[],15)
def test_metrics_are_present():
    result=TradeFlowMomentumDetector().analyze(book(),tape(["buy","sell"]*5),15)
    assert "momentum_activity" in result
    assert "last_bucket_volume_change_pct" in result["metrics"]
    assert "delta_change_since_previous_sample" in result["metrics"]


@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf"), "bad", None])
def test_invalid_lookback_is_rejected(invalid):
    with pytest.raises(ValueError):
        TradeFlowMomentumDetector().analyze(book(), tape(["buy"]*10), invalid)

def test_lookback_is_capped_and_echoed_as_normalized_value():
    result=TradeFlowMomentumDetector().analyze(book(), tape(["buy"]*10), 1000)
    assert result["lookback_seconds"] == 120.0

@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf"), "bad", None])
def test_invalid_detector_book_age_config_rejected(invalid):
    with pytest.raises(ValueError):
        TradeFlowMomentumDetector(max_book_age_seconds=invalid)

@pytest.mark.parametrize("invalid", [float("inf"), float("-inf")])
def test_invalid_trade_timestamp_overflow_ignored(invalid):
    result=TradeFlowMomentumDetector().analyze(book(), tape(["buy"]*8)+[
        {"side":"buy","price":100,"quantity":1,"received_timestamp_ms":invalid}
    ],15)
    assert result["trade_count"] == 8

def test_received_timestamp_zero_does_not_fallback_to_exchange_timestamp():
    now=int(time.time()*1000)
    rows=[{"side":"buy","price":100,"quantity":1,"received_timestamp_ms":0,"exchange_timestamp_ms":now}
           for _ in range(8)]
    result=TradeFlowMomentumDetector().analyze(book(),rows,15)
    assert result["trade_count"] == 0

def test_non_list_trade_payload_returns_insufficient_data():
    result=TradeFlowMomentumDetector().analyze(book(),None,15)
    assert result["trade_count"] == 0
    assert result["flow_classification"] == "INSUFFICIENT_DATA"

def test_exact_delta_ratio_thresholds():
    buys=[{"side":"buy","price":100,"quantity":1,"received_timestamp_ms":int(time.time()*1000)} for _ in range(6)]
    sells=[{"side":"sell","price":100,"quantity":1,"received_timestamp_ms":int(time.time()*1000)} for _ in range(4)]
    r=TradeFlowMomentumDetector().analyze(book(),buys+sells,15)
    assert r["metrics"]["delta_ratio"] == pytest.approx(0.2,abs=1e-5)
    assert r["flow_classification"] == "BUY_DOMINANT"

def test_symbol_history_isolated_and_bounded():
    detector=TradeFlowMomentumDetector(history_size=3)
    detector.analyze(book(),tape(["buy"]*10),15)
    second=book();second["symbol"]="ETHUSDT"
    detector.analyze(second,tape(["sell"]*10),15)
    assert len(detector._history["bybit:BTCUSDT"]) == 1
    assert len(detector._history["bybit:ETHUSDT"]) == 1
    for _ in range(5): detector.analyze(book(),tape(["buy"]*10),15)
    assert len(detector._history["bybit:BTCUSDT"]) == 3

def test_missing_sides_and_crossed_books_rejected():
    b=book();b["asks"]=[]
    with pytest.raises(ValueError): TradeFlowMomentumDetector().analyze(b,[],15)
    b=book();b["bids"]=[[100.02,3]]
    with pytest.raises(ValueError): TradeFlowMomentumDetector().analyze(b,[],15)

def test_nonfinite_trade_price_and_quantity_filtered():
    now=int(time.time()*1000)
    trades=tape(["buy"]*8)
    trades.extend([
        {"side":"buy","price":float("nan"),"quantity":1,"received_timestamp_ms":now},
        {"side":"sell","price":100,"quantity":float("inf"),"received_timestamp_ms":now},
        {"side":"unknown","price":100,"quantity":2,"received_timestamp_ms":now},
    ])
    result=TradeFlowMomentumDetector().analyze(book(),trades,15)
    assert result["trade_count"] == 8

def test_history_delta_acceleration_uses_prior_sample():
    detector=TradeFlowMomentumDetector()
    first=detector.analyze(book(),tape(["buy"]*10),15)
    second=detector.analyze(book(),tape(["sell"]*10),15)
    assert first["metrics"]["delta_change_since_previous_sample"] is None
    assert second["metrics"]["delta_change_since_previous_sample"] == -20

def test_score_is_bounded_and_matches_delta_ratio():
    result=TradeFlowMomentumDetector().analyze(book(),tape(["buy"]*20),15)
    assert -100 <= result["flow_strength_score"] <= 100
    assert result["flow_strength_score"] == pytest.approx(100)
