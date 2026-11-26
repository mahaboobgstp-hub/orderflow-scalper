import pytest
from app.services.nine_layer_decision_engine import NineLayerDecisionEngine, LAYER_NAMES

@pytest.fixture
def engine():
    return NineLayerDecisionEngine({"decision_score_threshold":55,"directional_conflict_ratio":0.65})

def strong_buy_inputs():
    return {
        "imbalance":{"metrics":{"weighted_imbalance":0.95},"quality":{"score":95}},
        "absorption":{"metrics":{"buy_absorption_score":0.0,"sell_absorption_score":0.8},"quality":{"score":90}},
        "zones":{"zones":[{"interaction_state":"BREAKOUT_UP","zone_price":100}]},
        "trade_flow":{"metrics":{"delta_ratio":0.95,"price_move_pct":0.5,"momentum_activity":"ACCELERATING"},"trade_count":40},
        "market":{"spread_pct":0.02,"quote_volume_24h":50_000_000,"range_24h_pct":4,"price_change_24h_pct":25},
        "broader_context":{"score":50,"confidence":80,"reasons":["Synthetic bullish context"]},
    }

def allow_risk():
    return {"allowed":True,"blockers":[],"equity":10000}

def test_all_nine_layers_present_and_safe_paper_only(engine):
    r=engine.evaluate("BTCUSDT",strong_buy_inputs(),allow_risk())
    assert len(r["layers"])==9
    assert r["mode"]=="PAPER_ONLY" and r["live_execution_enabled"] is False
    assert r["paper_only"] is True

def test_synthetic_aligned_bullish_layers_produce_buy(engine):
    r=engine.evaluate("BTCUSDT",strong_buy_inputs(),allow_risk())
    assert r["decision"]=="BUY" and r["entry_eligible"] is True

def test_conflicting_bearish_layers_do_not_allow_buy(engine):
    x=strong_buy_inputs()
    x["trade_flow"]["metrics"]["delta_ratio"]=-0.95
    x["trade_flow"]["metrics"]["price_move_pct"]=-0.5
    x["zones"]["zones"][0]["interaction_state"]="BREAKOUT_DOWN"
    r=engine.evaluate("BTCUSDT",x,allow_risk())
    assert r["decision"] in ("SELL","HOLD")
    assert r["decision"]!="BUY"

@pytest.mark.parametrize("critical",["imbalance","trade_flow"])
def test_missing_critical_layer_fails_closed(engine,critical):
    x=strong_buy_inputs()
    if critical=="imbalance": x.pop("imbalance")
    else:
        x["trade_flow"]["metrics"].pop("delta_ratio")
        x["trade_flow"]["metrics"].pop("price_move_pct")
    r=engine.evaluate("BTCUSDT",x,allow_risk())
    assert r["decision"]=="REJECT"
    expected="order_book_imbalance" if critical=="imbalance" else "aggressive_order_flow"
    assert expected in r["critical_unavailable_layers"]

@pytest.mark.parametrize("market",[
    {"spread_pct":0.30,"quote_volume_24h":50_000_000,"range_24h_pct":4,"price_change_24h_pct":25},
    {"spread_pct":0.02,"quote_volume_24h":1_000_000,"range_24h_pct":4,"price_change_24h_pct":25},
    {"spread_pct":None,"quote_volume_24h":50_000_000,"range_24h_pct":4,"price_change_24h_pct":25},
])
def test_l6_conditions_block_entry(engine,market):
    x=strong_buy_inputs(); x["market"]=market
    r=engine.evaluate("BTCUSDT",x,allow_risk())
    assert r["decision"]=="REJECT" and r["entry_eligible"] is False

def test_risk_blocker_rejects_strong_signal(engine):
    r=engine.evaluate("BTCUSDT",strong_buy_inputs(),{"allowed":False,"blockers":["DAILY_LOSS_LIMIT_REACHED"]})
    assert r["decision"]=="REJECT"
    assert r["layers"]["risk_execution"]["direction"]=="BLOCK"

def test_momentum_direction_independent_of_trade_delta(engine):
    x=strong_buy_inputs()
    x["trade_flow"]["metrics"]["delta_ratio"]=-1.0
    x["trade_flow"]["metrics"]["price_move_pct"]=0.4
    r=engine.evaluate("BTCUSDT",x,allow_risk())
    assert r["layers"]["momentum"]["direction"]=="BUY"
    assert r["layers"]["aggressive_order_flow"]["direction"]=="SELL"

def test_neutral_evidence_produces_hold(engine):
    x=strong_buy_inputs()
    x["imbalance"]["metrics"]["weighted_imbalance"]=0.0
    x["absorption"]["metrics"]={"buy_absorption_score":0.0,"sell_absorption_score":0.0}
    x["zones"]["zones"][0]["interaction_state"]="POSSIBLE_REJECTION"
    x["trade_flow"]["metrics"]["delta_ratio"]=0.0
    x["trade_flow"]["metrics"]["price_move_pct"]=0.0
    x["market"]["price_change_24h_pct"]=0.0
    x["broader_context"]["score"]=0
    assert engine.evaluate("BTCUSDT",x,allow_risk())["decision"]=="HOLD"

def test_nonfinite_critical_inputs_are_unavailable(engine):
    x=strong_buy_inputs()
    x["imbalance"]["metrics"]["weighted_imbalance"]=float("nan")
    x["trade_flow"]["metrics"]["delta_ratio"]=float("inf")
    r=engine.evaluate("BTCUSDT",x,allow_risk())
    assert not r["layers"]["order_book_imbalance"]["available"]
    assert not r["layers"]["aggressive_order_flow"]["available"]
    assert r["decision"]=="REJECT"

def test_missing_risk_permission_fails_closed(engine):
    assert engine.evaluate("BTCUSDT",strong_buy_inputs(),{})["decision"]=="REJECT"

def test_invalid_weight_overrides_are_ignored(engine):
    e=NineLayerDecisionEngine({"layer_weights":{"momentum":999,"order_book_imbalance":0}})
    assert e.weights["momentum"]==12 and e.weights["order_book_imbalance"]==0


def test_nine_layer_trace_schema_is_complete_and_bounded(engine):
    result = engine.evaluate("BTCUSDT", strong_buy_inputs(), allow_risk())
    assert set(result["layers"]) == set(LAYER_NAMES)
    required_fields = {"layer", "score", "direction", "confidence", "available", "reasons", "data"}
    for name in LAYER_NAMES:
        record = result["layers"][name]
        assert set(record) == required_fields
        assert record["layer"] == name
        assert record["direction"] in ("BUY", "SELL", "NEUTRAL", "BLOCK")
        assert isinstance(record["available"], bool)
        assert isinstance(record["reasons"], list)
        # Layer evidence is intentionally heterogeneous: structured objects or zone lists.
        assert isinstance(record["data"], (dict, list))
        assert type(record["confidence"]) in (int, float)
        assert 0 <= record["confidence"] <= 100
        if record["score"] is not None:
            assert type(record["score"]) in (int, float)
            assert -100 <= record["score"] <= 100
