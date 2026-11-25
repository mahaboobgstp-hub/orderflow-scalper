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

def test_fixed_stop_loss_auto_closes_long():
    e=PaperTradingEngine(10000)
    e.submit({"symbol":"BTCUSDT","side":"long","quantity":1,"price":100,"stop_loss_price":95})
    r=e.mark("BTCUSDT",94)
    assert r["auto_closed"] is True
    assert r["closed_trade"]["close_reason"]=="STOP_LOSS"

def test_fixed_take_profit_auto_closes_short():
    e=PaperTradingEngine(10000)
    e.submit({"symbol":"ETHUSDT","side":"short","quantity":1,"price":100,"take_profit_price":90})
    r=e.mark("ETHUSDT",89)
    assert r["auto_closed"] is True
    assert r["closed_trade"]["close_reason"]=="TAKE_PROFIT"

def test_trailing_stop_loss_follows_long_price_and_exits():
    e=PaperTradingEngine(10000)
    e.submit({"symbol":"BTCUSDT","side":"long","quantity":1,"price":100,"tsl_enabled":True,"tsl_distance_pct":5})
    e.mark("BTCUSDT",110)
    assert e.positions["BTCUSDT"]["tsl_price"]==104.5
    r=e.mark("BTCUSDT",104)
    assert r["auto_closed"] is True
    assert r["closed_trade"]["close_reason"]=="TRAILING_STOP_LOSS"

def test_trailing_take_profit_activation_and_retrace():
    e=PaperTradingEngine(10000)
    e.submit({"symbol":"BTCUSDT","side":"long","quantity":1,"price":100,"ttp_enabled":True,"ttp_activation_pct":5,"ttp_trail_pct":2})
    e.mark("BTCUSDT",106)
    assert e.positions["BTCUSDT"]["ttp_activated"] is True
    assert e.positions["BTCUSDT"]["ttp_price"]==103.88
    r=e.mark("BTCUSDT",103.5)
    assert r["auto_closed"] is True
    assert r["closed_trade"]["close_reason"]=="TRAILING_TAKE_PROFIT"

def test_invalid_stop_side_rejected():
    e=PaperTradingEngine(10000)
    with pytest.raises(ValueError):
        e.submit({"symbol":"X","side":"long","quantity":1,"price":100,"stop_loss_price":101})

def test_management_can_be_updated_on_open_position():
    e=PaperTradingEngine(10000)
    e.submit({"symbol":"X","side":"long","quantity":1,"price":100})
    r=e.update_management("X",{"stop_loss_price":95,"take_profit_price":110})
    assert r["updated"] is True
    assert e.positions["X"]["stop_loss_price"]==95
