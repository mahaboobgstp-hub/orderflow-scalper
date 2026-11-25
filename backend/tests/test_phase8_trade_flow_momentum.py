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
