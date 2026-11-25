import time
import pytest
from app.services.liquidity_zone_detector import LiquidityZoneDetector
from app.services.nine_layer_decision_engine import NineLayerDecisionEngine

def make_book(mid=100.0):
    return {"exchange":"bybit","symbol":"ETHUSDT","bids":[[mid-0.01,10],[mid-0.02,8]],"asks":[[mid+0.01,11],[mid+0.02,7]],
        "synchronized":True,"stale":False,"age_seconds":0.1,"integrity_error":None}

def trades(prices):
    now=int(time.time()*1000)
    return [{"price":p,"quantity":2,"side":"buy","received_timestamp_ms":now-i*100} for i,p in enumerate(prices)]

def test_zone_cluster_and_output_fields():
    d=LiquidityZoneDetector()
    result=d.analyze(make_book(100.02),trades([100,100.01,100.02,100.03]),lookback_seconds=30)
    assert result["zone_count"]>=1
    z=result["zones"][0]
    assert z["low"]<=z["center"]<=z["high"]
    assert "touch_count" in z and "interaction_state" in z
    assert result["current_displayed_depth_references"]["bid_liquidity_levels"]

def test_breakout_up_classification():
    d=LiquidityZoneDetector()
    t=trades([100,100.01,100.02,100.03])
    d.analyze(make_book(100.02),t,30)
    result=d.analyze(make_book(100.20),t,30)
    assert any(z["interaction_state"]=="BREAKOUT_UP" for z in result["zones"])

def test_reentry_reset_state():
    d=LiquidityZoneDetector()
    t=trades([100,100.01,100.02,100.03])
    d.analyze(make_book(100.02),t,30)
    d.analyze(make_book(100.20),t,30)
    result=d.analyze(make_book(100.02),t,30)
    assert any(z["interaction_state"]=="ZONE_RETEST_OR_REENTRY" for z in result["zones"])

def test_unsynchronized_or_stale_book_rejected():
    d=LiquidityZoneDetector()
    bad=make_book(); bad["synchronized"]=False
    with pytest.raises(ValueError): d.analyze(bad,[],30)
    bad=make_book(); bad["stale"]=True
    with pytest.raises(ValueError): d.analyze(bad,[],30)

def test_empty_trade_history_returns_empty_zones():
    result=LiquidityZoneDetector().analyze(make_book(),[],30)
    assert result["zones"]==[]

def test_possible_rejection_flag_is_defined_and_heuristic():
    d=LiquidityZoneDetector()
    # Tape includes zone interaction then a later timestamp outside the buffer.
    now=int(time.time()*1000)
    t=[
        {"price":100.00,"quantity":2,"side":"buy","received_timestamp_ms":now-300},
        {"price":100.01,"quantity":2,"side":"buy","received_timestamp_ms":now-200},
        {"price":100.20,"quantity":2,"side":"buy","received_timestamp_ms":now-100},
    ]
    result=d.analyze(make_book(100.20),t,30)
    assert result["zones"]
    assert all("possible_rejection" in z for z in result["zones"])
    assert any(z["possible_rejection"] for z in result["zones"])


@pytest.mark.parametrize("age",["bad",float("nan"),float("inf"),-0.1])
def test_invalid_book_age_rejected(age):
    bad=make_book()
    bad["age_seconds"]=age
    with pytest.raises(ValueError):
        LiquidityZoneDetector().analyze(bad,[],30)


def test_malformed_trade_records_are_ignored():
    result=LiquidityZoneDetector().analyze(make_book(),[
        None,{},{"price":"nan","quantity":3,"received_timestamp_ms":int(time.time()*1000)},
        {"price":100,"quantity":"bad","received_timestamp_ms":int(time.time()*1000)}
    ],30)
    assert result["zones"]==[]

def test_missing_book_side_and_crossed_book_rejected():
    detector=LiquidityZoneDetector()
    bad=make_book()
    bad["asks"]=[]
    with pytest.raises(ValueError):
        detector.analyze(bad,[],30)
    bad=make_book()
    bad["bids"]=[[100.01,1]]
    bad["asks"]=[[100.01,1]]
    with pytest.raises(ValueError):
        detector.analyze(bad,[],30)


def test_symbol_state_isolation_for_breakout_and_reentry():
    detector=LiquidityZoneDetector()
    t=trades([100.00,100.01,100.02,100.03])
    detector.analyze(make_book(100.02),t,30)
    # ETH breakout is observed; BTC uses the same price cluster but must not
    # inherit ETH's prior state because the detector key includes symbol.
    eth=make_book(100.20)
    eth["symbol"]="ETHUSDT"
    detector.analyze(eth,t,30)
    btc=make_book(100.02)
    btc["symbol"]="BTCUSDT"
    result=detector.analyze(btc,t,30)
    assert any(z["interaction_state"]=="IN_ZONE" for z in result["zones"])


def test_invalid_trade_timestamps_and_out_of_window_are_filtered():
    now=int(time.time()*1000)
    result=LiquidityZoneDetector().analyze(make_book(),[
        {"price":100.0,"quantity":2,"received_timestamp_ms":"bad"},
        {"price":100.01,"quantity":2,"received_timestamp_ms":now-100000},
        {"price":float("nan"),"quantity":2,"received_timestamp_ms":now},
        {"price":100.02,"quantity":2,"received_timestamp_ms":now+60000}
    ],30)
    assert result["zones"]==[]


def test_zone_limit_is_respected():
    d=LiquidityZoneDetector(max_zones=2,zone_band_pct=0.01)
    prices=[99.80,99.90,100.00,100.10,100.20,100.30,100.40]
    result=d.analyze(make_book(100.0),trades(prices),30)
    assert result["zone_count"]<=2


@pytest.mark.parametrize("lookback", [0, -1, float("nan"), float("inf"), "bad"])
def test_invalid_lookback_is_rejected(lookback):
    with pytest.raises((ValueError, TypeError)):
        LiquidityZoneDetector().analyze(make_book(), trades([100.0, 100.01]), lookback)


def test_breakout_boundary_is_not_triggered_at_exact_buffer():
    d=LiquidityZoneDetector(breakout_buffer_pct=0.05)
    t=trades([100,100.01,100.02,100.03])
    first=d.analyze(make_book(100.02),t,30)
    z=first["zones"][0]
    result=d.analyze(make_book(z["breakout_buffer_high"]),t,30)
    assert all(zone["interaction_state"] != "BREAKOUT_UP" for zone in result["zones"])


def test_breakout_state_and_rejection_flag_precedence_are_consistent():
    d=LiquidityZoneDetector()
    now=int(time.time()*1000)
    tape=[
        {"price":100.00,"quantity":2,"received_timestamp_ms":now-200},
        {"price":100.01,"quantity":2,"received_timestamp_ms":now-100},
        {"price":100.20,"quantity":2,"received_timestamp_ms":now},
    ]
    result=d.analyze(make_book(100.20),tape,30)
    for zone in result["zones"]:
        if zone["possible_rejection"]:
            assert zone["interaction_state"] in ("POSSIBLE_REJECTION", "BREAKOUT_UP", "BREAKOUT_DOWN")


def test_trade_input_order_does_not_change_zone_geometry_or_volume():
    base=trades([100,100.01,100.02,100.03,100.04])
    d1=LiquidityZoneDetector()
    d2=LiquidityZoneDetector()
    a=d1.analyze(make_book(100.02),base,30)["zones"]
    b=d2.analyze(make_book(100.02),list(reversed(base)),30)["zones"]
    geometry=lambda zs: sorted((z["low"],z["high"],z["center"],z["trade_volume_in_cluster"]) for z in zs)
    assert geometry(a)==geometry(b)


@pytest.mark.parametrize("timestamp", [float("inf"), float("-inf")])
def test_overflowing_trade_timestamps_are_ignored(timestamp):
    now=int(time.time()*1000)
    detector=LiquidityZoneDetector()
    result=detector.analyze(make_book(),[
        {"price":100.0,"quantity":2,"received_timestamp_ms":now},
        {"price":100.01,"quantity":2,"received_timestamp_ms":timestamp},
    ],30)
    assert result["zones"]


def test_zone_state_is_cleared_when_zone_disappears():
    detector=LiquidityZoneDetector()
    t=trades([100.0,100.01,100.02])
    detector.analyze(make_book(100.02),t,30)
    assert detector._previous_state["bybit:ETHUSDT"]
    detector.analyze(make_book(100.02),[],30)
    assert detector._previous_state["bybit:ETHUSDT"] == {}


def test_possible_rejection_does_not_mask_confirmed_mid_breakout_classification():
    detector=LiquidityZoneDetector()
    now=int(time.time()*1000)
    tape=[
        {"price":100.00,"quantity":2,"received_timestamp_ms":now-300},
        {"price":100.01,"quantity":2,"received_timestamp_ms":now-200},
        {"price":100.20,"quantity":2,"received_timestamp_ms":now-100},
    ]
    result=detector.analyze(make_book(100.20),tape,30)
    assert result["zones"]
    assert any(z["possible_rejection"] for z in result["zones"])
    assert any(z["interaction_state"] == "BREAKOUT_UP" for z in result["zones"])


def test_nine_layer_engine_consumes_layer3_breakout_as_directional_evidence():
    engine=NineLayerDecisionEngine()
    result=engine.evaluate("ETHUSDT",{"zones":{"zones":[{"interaction_state":"BREAKOUT_UP"}]}},risk={"allowed":True,"blockers":[]})
    layer=result["layers"]["liquidity_breakout"]
    assert layer["available"] is True
    assert layer["direction"]=="BUY"
    assert layer["score"]==70


def test_nine_layer_engine_keeps_possible_rejection_non_directional():
    engine=NineLayerDecisionEngine()
    result=engine.evaluate("ETHUSDT",{"zones":{"zones":[{"interaction_state":"POSSIBLE_REJECTION"}]}},risk={"allowed":True,"blockers":[]})
    layer=result["layers"]["liquidity_breakout"]
    assert layer["available"] is True
    assert layer["direction"]=="NEUTRAL"
    assert layer["score"]==0


def test_nine_layer_engine_marks_missing_layer3_zones_unavailable():
    engine=NineLayerDecisionEngine()
    result=engine.evaluate("ETHUSDT",{"zones":{"zones":[]}},risk={"allowed":True,"blockers":[]})
    layer=result["layers"]["liquidity_breakout"]
    assert layer["available"] is False
    assert layer["score"] is None
