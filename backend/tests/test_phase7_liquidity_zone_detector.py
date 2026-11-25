import time
import pytest
from app.services.liquidity_zone_detector import LiquidityZoneDetector

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
