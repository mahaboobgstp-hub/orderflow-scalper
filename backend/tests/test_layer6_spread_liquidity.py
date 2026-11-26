import pytest
from app.services.nine_layer_decision_engine import NineLayerDecisionEngine

def eval_market(market,config=None):
    return NineLayerDecisionEngine(config).evaluate("BTCUSDT",{"market":market},risk={"allowed":True,"blockers":[]})

def l6(result):
    return result["layers"]["spread_liquidity"]

def test_layer6_good_spread_and_volume_pass_neutral_gate():
    r=eval_market({"spread_pct":0.08,"quote_volume_24h":5_000_000})
    assert l6(r)["available"]
    assert l6(r)["direction"]=="NEUTRAL"
    assert l6(r)["score"]==60
    assert l6(r)["data"]["passed"] is True
    assert r["decision"]!="REJECT"

def test_layer6_spread_above_limit_blocks():
    r=eval_market({"spread_pct":0.13,"quote_volume_24h":5_000_000})
    assert l6(r)["direction"]=="BLOCK"
    assert l6(r)["score"]==-100
    assert r["decision"]=="REJECT"

def test_layer6_volume_below_minimum_blocks():
    r=eval_market({"spread_pct":0.08,"quote_volume_24h":4_999_999})
    assert l6(r)["direction"]=="BLOCK"
    assert l6(r)["score"]==-60
    assert r["decision"]=="REJECT"

@pytest.mark.parametrize("market",[
    {}, {"spread_pct":0.08}, {"quote_volume_24h":5_000_000},
    {"spread_pct":None,"quote_volume_24h":5_000_000},
    {"spread_pct":0.08,"quote_volume_24h":None},
    {"spread_pct":"bad","quote_volume_24h":5_000_000},
    {"spread_pct":0.08,"quote_volume_24h":"bad"},
    {"spread_pct":float("nan"),"quote_volume_24h":5_000_000},
    {"spread_pct":0.08,"quote_volume_24h":float("inf")},
])
def test_layer6_missing_or_invalid_market_data_fails_closed(market):
    r=eval_market(market)
    assert l6(r)["direction"]=="BLOCK"
    assert r["decision"]=="REJECT"

@pytest.mark.parametrize("spread,volume",[
    (-0.01,5_000_000),(0.08,-1),(float("-inf"),5_000_000),
    (0.08,float("-inf"))
])
def test_layer6_negative_or_nonfinite_market_values_block(spread,volume):
    r=eval_market({"spread_pct":spread,"quote_volume_24h":volume})
    assert l6(r)["direction"]=="BLOCK"
    assert r["decision"]=="REJECT"

def test_layer6_exact_thresholds_are_accepted():
    r=eval_market({"spread_pct":0.12,"quote_volume_24h":5_000_000})
    assert l6(r)["direction"]=="NEUTRAL"
    assert l6(r)["score"]==60

def test_layer6_configurable_thresholds_apply():
    r=eval_market({"spread_pct":0.20,"quote_volume_24h":2_500_000},
        {"max_spread_pct":0.25,"min_24h_volume_usd":2_000_000})
    assert l6(r)["direction"]=="NEUTRAL"
    assert l6(r)["data"]["spread_limit_pct"]==0.25
    assert l6(r)["data"]["volume_minimum"]==2_000_000

@pytest.mark.parametrize("config",[
    {"max_spread_pct":0}, {"max_spread_pct":-1},
    {"min_24h_volume_usd":0}, {"min_24h_volume_usd":-5},
    {"max_spread_pct":float("nan")}, {"min_24h_volume_usd":float("inf")}
])
def test_layer6_invalid_threshold_config_falls_back_to_safe_defaults(config):
    r=eval_market({"spread_pct":0.08,"quote_volume_24h":5_000_000},config)
    assert l6(r)["direction"]=="NEUTRAL"
    assert l6(r)["data"]["spread_limit_pct"]==0.12
    assert l6(r)["data"]["volume_minimum"]==1_000_000
