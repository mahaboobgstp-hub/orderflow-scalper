import asyncio
import time
import pytest
from fastapi import HTTPException
from app import main

def api_book():
    mid=100
    return {"exchange":"bybit","symbol":"BTCUSDT","bids":[[mid-.01,5],[mid-.02,3]],"asks":[[mid+.01,4],[mid+.02,2]],
        "synchronized":True,"stale":False,"age_seconds":.1,"integrity_error":None}

def api_tape():
    now=int(time.time()*1000)
    return [{"side":"buy" if i%2==0 else "sell","price":100,"quantity":1,
             "received_timestamp_ms":now-i*100} for i in range(12)]

class StubMarket:
    def __init__(self,book): self.book=book
    def get_book(self,exchange,symbol): return self.book
    def get_recent_trades(self,exchange,symbol,limit): return api_tape()[:limit]

@pytest.fixture(autouse=True)
def restore_main_app_state():
    old_market=getattr(main.app.state,"unified_market_data",None)
    old_trade_flow=getattr(main.app.state,"trade_flow_momentum_detector",None)
    yield
    if old_market is None:
        if hasattr(main.app.state,"unified_market_data"): delattr(main.app.state,"unified_market_data")
    else:
        main.app.state.unified_market_data=old_market
    if old_trade_flow is None:
        if hasattr(main.app.state,"trade_flow_momentum_detector"): delattr(main.app.state,"trade_flow_momentum_detector")
    else:
        main.app.state.trade_flow_momentum_detector=old_trade_flow

def setup(book):
    main.app.state.unified_market_data=StubMarket(book)
    main.app.state.trade_flow_momentum_detector=main.TradeFlowMomentumDetector()

def test_trade_flow_route_returns_expected_shape():
    setup(api_book())
    result=asyncio.run(main.analyze_trade_flow("bybit","BTCUSDT",15,500))
    assert result["engine"]=="phase8_trade_flow_momentum"
    assert result["exchange"]=="bybit" and result["symbol"]=="BTCUSDT"
    assert result["trade_count"]==12
    assert "delta_ratio" in result["metrics"]

def test_trade_flow_route_rejects_unknown_exchange():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.analyze_trade_flow("unknown","BTCUSDT",15,500))
    assert exc.value.status_code==400

def test_trade_flow_route_returns_404_when_book_missing():
    setup(None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.analyze_trade_flow("bybit","BTCUSDT",15,500))
    assert exc.value.status_code==404

def test_trade_flow_route_maps_invalid_book_to_422():
    b=api_book(); b["synchronized"]=False
    setup(b)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.analyze_trade_flow("bybit","BTCUSDT",15,500))
    assert exc.value.status_code==422

def test_trade_flow_status_reports_read_only_mode():
    result=asyncio.run(main.trade_flow_status())
    assert result["mode"]=="read_only_research"
    assert result["phase"]==8
