import asyncio
import time
import pytest
from fastapi import HTTPException
from app import main

def make_book():
    now=int(time.time()*1000)
    return {
        "exchange":"bybit","symbol":"ETHUSDT","bids":[[100.00,10],[99.99,5]],
        "asks":[[100.02,11],[100.03,6]],"synchronized":True,"stale":False,
        "age_seconds":0.1,"integrity_error":None,
    }

def make_trades():
    now=int(time.time()*1000)
    return [
        {"price":100.00,"quantity":2,"received_timestamp_ms":now-200},
        {"price":100.01,"quantity":2,"received_timestamp_ms":now-100},
    ]

class StubMarketData:
    def __init__(self, book):
        self.book=book
    def get_book(self, exchange, symbol):
        return self.book
    def get_recent_trades(self, exchange, symbol, limit):
        return make_trades()

def setup_api(book):
    main.app.state.unified_market_data=StubMarketData(book)
    main.app.state.liquidity_zone_detector=main.LiquidityZoneDetector()

def test_liquidity_zone_api_returns_detector_result():
    setup_api(make_book())
    result=asyncio.run(main.analyze_liquidity_zones("bybit","ETHUSDT",30,500))
    assert result["exchange"]=="bybit"
    assert result["symbol"]=="ETHUSDT"
    assert result["zones"]
    assert result["detector"]=="phase7_liquidity_zone_breakout"

def test_liquidity_zone_api_rejects_unsupported_exchange():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.analyze_liquidity_zones("unknown","ETHUSDT",30,500))
    assert exc.value.status_code==400

def test_liquidity_zone_api_returns_404_when_book_missing():
    setup_api(None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.analyze_liquidity_zones("bybit","ETHUSDT",30,500))
    assert exc.value.status_code==404

def test_liquidity_zone_api_maps_invalid_book_to_422():
    bad=make_book()
    bad["age_seconds"]=float("nan")
    setup_api(bad)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.analyze_liquidity_zones("bybit","ETHUSDT",30,500))
    assert exc.value.status_code==422
