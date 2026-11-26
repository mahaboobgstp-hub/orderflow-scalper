from app.services.nine_layer_decision_engine import NineLayerDecisionEngine

def test_layer4_buy_flow_consumed_as_directional_decision_evidence():
    engine=NineLayerDecisionEngine()
    result=engine.evaluate("BTCUSDT",{"trade_flow":{"metrics":{"delta_ratio":1.0},"trade_count":10}},risk={"allowed":True,"blockers":[]})
    layer=result["layers"]["aggressive_order_flow"]
    assert layer["available"] is True
    assert layer["score"]==100
    assert layer["direction"]=="BUY"

def test_layer4_sell_flow_consumed_as_directional_decision_evidence():
    engine=NineLayerDecisionEngine()
    result=engine.evaluate("BTCUSDT",{"trade_flow":{"metrics":{"delta_ratio":-1.0},"trade_count":10}},risk={"allowed":True,"blockers":[]})
    layer=result["layers"]["aggressive_order_flow"]
    assert layer["available"] is True
    assert layer["score"]==-100
    assert layer["direction"]=="SELL"

def test_layer4_missing_delta_is_not_silently_available():
    engine=NineLayerDecisionEngine()
    result=engine.evaluate("BTCUSDT",{"trade_flow":{"metrics":{},"trade_count":0}},risk={"allowed":True,"blockers":[]})
    layer=result["layers"]["aggressive_order_flow"]
    assert layer["available"] is False
    assert layer["score"] is None

def test_layer4_balanced_flow_is_neutral():
    engine=NineLayerDecisionEngine()
    result=engine.evaluate("BTCUSDT",{"trade_flow":{"metrics":{"delta_ratio":0.0},"trade_count":10}},risk={"allowed":True,"blockers":[]})
    layer=result["layers"]["aggressive_order_flow"]
    assert layer["available"] is True
    assert layer["score"]==0
    assert layer["direction"]=="NEUTRAL"

def test_layer2_buy_absorption_is_bearish_caution():
    engine=NineLayerDecisionEngine()
    result=engine.evaluate("BTCUSDT",{"absorption":{"metrics":{"buy_absorption_score":0.9,"sell_absorption_score":0.0},"quality":{"score":80}}},risk={"allowed":True,"blockers":[]})
    layer=result["layers"]["absorption"]
    assert layer["direction"]=="SELL"
    assert layer["score"]==-90

def test_layer2_sell_absorption_is_bullish_caution():
    engine=NineLayerDecisionEngine()
    result=engine.evaluate("BTCUSDT",{"absorption":{"metrics":{"buy_absorption_score":0.0,"sell_absorption_score":0.9},"quality":{"score":80}}},risk={"allowed":True,"blockers":[]})
    layer=result["layers"]["absorption"]
    assert layer["direction"]=="BUY"
    assert layer["score"]==90
