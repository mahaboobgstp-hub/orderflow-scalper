import pytest
from app.services.backtesting import BacktestEngine

def sample_candles(n=80):
    data=[]
    p=100.0
    for i in range(n):
        p += 0.5 if i<40 else -0.4
        data.append({"timestamp":i,"open":p,"high":p+0.5,"low":p-0.5,"close":p})
    return data

def test_backtest_returns_metrics_and_closed_trades():
    result=BacktestEngine().run(sample_candles(),{"ema_fast":4,"ema_slow":8})
    assert result["mode"]=="OFFLINE_HISTORICAL_CANDLES"
    assert "summary" in result and "profit_factor" in result["summary"]
    assert all("net_pnl" in t for t in result["trades"])

def test_invalid_candle_data_rejected():
    with pytest.raises(ValueError):
        BacktestEngine().run([{"open":1,"high":1,"low":1,"close":1}]*5,{"ema_slow":36})

def test_bad_ohlc_rejected():
    candles=sample_candles()
    candles[0]["high"]=1
    with pytest.raises(ValueError): BacktestEngine().run(candles,{"ema_fast":4,"ema_slow":8})

def test_parameters_validated():
    with pytest.raises(ValueError): BacktestEngine().run(sample_candles(),{"ema_fast":40,"ema_slow":10})
