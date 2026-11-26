import pytest
from app.services.risk_management import RiskManagementEngine

def test_position_sizing_risk_based():
    r=RiskManagementEngine().calculate({"account_equity":10000,"entry_price":100,"stop_loss_price":98,"side":"long","leverage":3})
    assert r["risk_budget"]==50
    assert r["position_quantity"]==25
    assert r["estimated_loss_at_stop"]==50
    assert r["estimated_initial_margin"]==pytest.approx(833.333333)

def test_short_stop_direction():
    r=RiskManagementEngine().calculate({"account_equity":5000,"entry_price":50,"stop_loss_price":52,"side":"short"})
    assert r["position_quantity"]==12.5
    with pytest.raises(ValueError): RiskManagementEngine().calculate({"account_equity":5000,"entry_price":50,"stop_loss_price":48,"side":"short"})

def test_notional_cap_applies():
    r=RiskManagementEngine().calculate({"account_equity":1000,"entry_price":100,"stop_loss_price":99.9,"side":"long","risk_per_trade_pct":1,"max_position_notional_pct":10})
    assert r["position_limited_by_notional_cap"] is True
    assert r["position_notional"]==100

def test_reject_invalid_inputs_and_leverage():
    e=RiskManagementEngine()
    with pytest.raises(ValueError): e.calculate({"account_equity":0,"entry_price":10,"stop_loss_price":9,"side":"long"})
    with pytest.raises(ValueError): e.calculate({"account_equity":1000,"entry_price":10,"stop_loss_price":9,"side":"long","leverage":10})

def test_portfolio_guard_blocks_at_limits():
    r=RiskManagementEngine().evaluate_portfolio(10000,daily_realized_loss=200,open_risk=251,open_positions=2,consecutive_losses=1)
    assert r["allowed_to_consider_new_trade"] is False
    assert "DAILY_LOSS_LIMIT_REACHED" in r["blockers"]
    assert "OPEN_RISK_LIMIT_WOULD_BE_EXCEEDED" in r["blockers"]

def test_guard_allows_within_limits():
    r=RiskManagementEngine().evaluate_portfolio(10000,daily_realized_loss=0,open_risk=50,open_positions=1,consecutive_losses=0)
    assert r["allowed_to_consider_new_trade"] is True
