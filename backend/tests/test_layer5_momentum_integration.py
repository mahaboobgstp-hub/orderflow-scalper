from app.services.nine_layer_decision_engine import NineLayerDecisionEngine

def test_layer5_direction_comes_from_price_progress_not_l4_delta():
    e=NineLayerDecisionEngine()
    r=e.evaluate("BTCUSDT",{"trade_flow":{"trade_count":10,"flow_strength_score":100,"momentum_activity":"ACCELERATING","metrics":{"delta_ratio":1.0,"price_move_pct":0.25}}},risk={"allowed":True,"blockers":[]})
    l4=r["layers"]["aggressive_order_flow"]; l5=r["layers"]["momentum"]
    assert l4["direction"]=="BUY"
    assert l5["direction"]=="BUY"
    assert l5["score"]==50
    assert l5["data"]["direction_source"]=="price_move_pct"

def test_layer5_can_conflict_with_layer4_when_price_moves_opposite():
    e=NineLayerDecisionEngine()
    r=e.evaluate("BTCUSDT",{"trade_flow":{"trade_count":10,"flow_strength_score":100,"metrics":{"delta_ratio":1.0,"price_move_pct":-0.25}}},risk={"allowed":True,"blockers":[]})
    assert r["layers"]["aggressive_order_flow"]["direction"]=="BUY"
    assert r["layers"]["momentum"]["direction"]=="SELL"
    assert r["layers"]["momentum"]["score"]==-50

def test_layer5_missing_price_move_is_unavailable():
    e=NineLayerDecisionEngine()
    r=e.evaluate("BTCUSDT",{"trade_flow":{"trade_count":10,"flow_strength_score":100,"metrics":{"delta_ratio":1.0}}},risk={"allowed":True,"blockers":[]})
    assert r["layers"]["momentum"]["available"] is False
    assert r["layers"]["momentum"]["score"] is None

def test_layer5_low_trade_count_is_unavailable():
    e=NineLayerDecisionEngine()
    r=e.evaluate("BTCUSDT",{"trade_flow":{"trade_count":3,"metrics":{"price_move_pct":0.5}}},risk={"allowed":True,"blockers":[]})
    assert r["layers"]["momentum"]["available"] is False

def test_layer5_score_clamped_and_threshold_direction():
    e=NineLayerDecisionEngine()
    r=e.evaluate("BTCUSDT",{"trade_flow":{"trade_count":8,"metrics":{"price_move_pct":99}}},risk={"allowed":True,"blockers":[]})
    assert r["layers"]["momentum"]["score"]==100
    assert r["layers"]["momentum"]["direction"]=="BUY"
    r=e.evaluate("BTCUSDT",{"trade_flow":{"trade_count":8,"metrics":{"price_move_pct":-99}}},risk={"allowed":True,"blockers":[]})
    assert r["layers"]["momentum"]["score"]==-100
    assert r["layers"]["momentum"]["direction"]=="SELL"

def test_layer5_scale_configuration():
    e=NineLayerDecisionEngine({"momentum_price_move_scale_pct":1.0})
    r=e.evaluate("BTCUSDT",{"trade_flow":{"trade_count":8,"metrics":{"price_move_pct":0.25}}},risk={"allowed":True,"blockers":[]})
    assert r["layers"]["momentum"]["score"]==25

import pytest

@pytest.mark.parametrize("bad",["invalid",None,float("nan"),float("inf"),float("-inf")])
def test_layer5_invalid_min_trade_config_falls_back_safely(bad):
    e=NineLayerDecisionEngine({"momentum_min_trades":bad})
    r=e.evaluate("BTCUSDT",{"trade_flow":{"trade_count":8,"metrics":{"price_move_pct":0.5}}},risk={"allowed":True,"blockers":[]})
    assert r["layers"]["momentum"]["available"] is True

@pytest.mark.parametrize("bad",[0,-1,float("nan"),float("inf"),"bad",None])
def test_layer5_invalid_scale_config_uses_default(bad):
    e=NineLayerDecisionEngine({"momentum_price_move_scale_pct":bad})
    r=e.evaluate("BTCUSDT",{"trade_flow":{"trade_count":8,"metrics":{"price_move_pct":0.5}}},risk={"allowed":True,"blockers":[]})
    assert r["layers"]["momentum"]["score"]==100

from app.services.trade_flow_momentum import TradeFlowMomentumDetector
import time

def valid_book():
    return {"exchange":"bybit","symbol":"BTCUSDT","bids":[[99.99,4]],"asks":[[100.01,4]],
            "synchronized":True,"stale":False,"age_seconds":0.1,"integrity_error":None}

def rising_tape():
    now=int(time.time()*1000)
    return [{"side":"buy","price":100+i*0.05,"quantity":1.0,"received_timestamp_ms":now-(7-i)*500} for i in range(8)]

def falling_tape():
    now=int(time.time()*1000)
    return [{"side":"buy","price":100-i*0.05,"quantity":1.0,"received_timestamp_ms":now-(7-i)*500} for i in range(8)]

def test_detector_price_progress_feeds_layer5_rising_prices():
    detector=TradeFlowMomentumDetector()
    output=detector.analyze(valid_book(),rising_tape(),15)
    decision=NineLayerDecisionEngine().evaluate("BTCUSDT",{"trade_flow":output},risk={"allowed":True,"blockers":[]})
    assert output["metrics"]["price_move_pct"]>0
    assert decision["layers"]["momentum"]["direction"]=="BUY"
    assert decision["layers"]["momentum"]["available"] is True

def test_detector_price_progress_feeds_layer5_falling_prices_despite_buy_delta():
    detector=TradeFlowMomentumDetector()
    output=detector.analyze(valid_book(),falling_tape(),15)
    decision=NineLayerDecisionEngine().evaluate("BTCUSDT",{"trade_flow":output},risk={"allowed":True,"blockers":[]})
    assert output["metrics"]["delta_ratio"]==1.0
    assert output["metrics"]["price_move_pct"]<0
    assert decision["layers"]["aggressive_order_flow"]["direction"]=="BUY"
    assert decision["layers"]["momentum"]["direction"]=="SELL"
