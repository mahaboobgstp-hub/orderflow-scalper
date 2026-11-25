import pytest
from app.services.paper_trading import PaperTradingEngine

def test_long_position_mark_and_close_profit():
    e=PaperTradingEngine(10000)
    result=e.submit({"symbol":"BTCUSDT","side":"long","quantity":1,"price":100,"leverage":2})
    assert result["order"]["status"]=="FILLED_SIMULATED"
    marked=e.mark("BTCUSDT",110)
    assert marked["position"]["unrealized_pnl"]==10
    closed=e.close("BTCUSDT",110)
    assert closed["net_pnl"]>0
    assert e.account()["open_position_count"]==0

def test_short_pnl_direction():
    e=PaperTradingEngine(10000)
    e.submit({"symbol":"ETHUSDT","side":"short","quantity":2,"price":100,"leverage":1})
    assert e.mark("ETHUSDT",90)["position"]["unrealized_pnl"]==20
    assert e.close("ETHUSDT",90)["net_pnl"]>0

def test_margin_and_fee_requirements():
    e=PaperTradingEngine(100)
    with pytest.raises(ValueError): e.submit({"symbol":"X","side":"long","quantity":1,"price":200,"leverage":1})
    with pytest.raises(ValueError): e.submit({"symbol":"X","side":"long","quantity":1,"price":10,"leverage":6})

def test_duplicate_symbol_position_rejected():
    e=PaperTradingEngine()
    e.submit({"symbol":"BTCUSDT","side":"long","quantity":1,"price":10})
    with pytest.raises(ValueError): e.submit({"symbol":"BTCUSDT","side":"short","quantity":1,"price":10})

def test_reset_clears_session():
    e=PaperTradingEngine(1000); e.submit({"symbol":"X","side":"long","quantity":1,"price":10})
    e.reset(2000)
    assert e.account()["equity"]==2000 and not e.positions
