from datetime import datetime, timezone
from app.services.risk_management import RiskManagementEngine

DAY_MS = int(datetime(2026, 11, 26, 12, tzinfo=timezone.utc).timestamp() * 1000)
def _closed(pnls):
    return [{"net_pnl": pnl, "closed_at_ms": DAY_MS-i*1000} for i,pnl in enumerate(pnls)]

def test_phase_e_daily_loss_uses_net_pnl_not_gross_loss_sum():
    e=RiskManagementEngine(); r=e.evaluate_runtime_gate(account_equity=10000,closed_trades=_closed([-80,50]),orders=[],positions={},symbol="BTCUSDT",config={"max_daily_loss_pct":2},now_ms=DAY_MS)
    assert r["daily_net_pnl"]==-30 and r["daily_realized_loss"]==30 and r["allowed"]

def test_phase_e_daily_loss_limit_blocks():
    e=RiskManagementEngine(); r=e.evaluate_runtime_gate(account_equity=10000,closed_trades=_closed([-200]),orders=[],positions={},symbol="BTCUSDT",config={"max_daily_loss_pct":2},now_ms=DAY_MS)
    assert "DAILY_LOSS_LIMIT_REACHED" in r["blockers"]

def test_phase_e_trade_count_limit_blocks():
    e=RiskManagementEngine(); orders=[{"created_at_ms":DAY_MS,"status":"FILLED_SIMULATED"} for _ in range(3)]
    r=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=orders,positions={},symbol="ETHUSDT",config={"max_trades_per_day":3,"cooldown_seconds":0},now_ms=DAY_MS)
    assert r["daily_trade_count"]==3 and "MAX_TRADES_PER_DAY_REACHED" in r["blockers"]

def test_phase_e_cooldown_expires_correctly():
    e=RiskManagementEngine(); orders=[{"created_at_ms":DAY_MS-10000,"status":"FILLED_SIMULATED"}]
    a=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=orders,positions={},symbol="BTCUSDT",config={"cooldown_seconds":30},now_ms=DAY_MS)
    b=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=orders,positions={},symbol="BTCUSDT",config={"cooldown_seconds":30},now_ms=DAY_MS+31000)
    assert "COOLDOWN_ACTIVE" in a["blockers"] and "COOLDOWN_ACTIVE" not in b["blockers"]

def test_phase_e_kill_switch_blocks_until_reset():
    e=RiskManagementEngine(); e.set_kill_switch(True,"test halt")
    a=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions={},symbol="BTCUSDT",now_ms=DAY_MS)
    assert "RISK_KILL_SWITCH_ACTIVE" in a["blockers"]
    e.set_kill_switch(False)
    assert e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions={},symbol="BTCUSDT",now_ms=DAY_MS)["allowed"]

def test_phase_e_book_and_aggregate_open_risk_block():
    e=RiskManagementEngine(); pos={"ETHUSDT":{"side":"long","entry_price":100,"stop_loss_price":95,"quantity":2}}
    r=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions=pos,symbol="BTCUSDT",config={"risk_per_trade_pct":0.5,"max_total_open_risk_pct":0.1,"cooldown_seconds":0},synchronized_book=False,now_ms=DAY_MS)
    assert r["open_stop_risk"]==10
    assert "SYNCHRONIZED_BOOK_UNAVAILABLE" in r["blockers"] and "TOTAL_OPEN_RISK_LIMIT_WOULD_BE_EXCEEDED" in r["blockers"]

def test_phase_e_position_without_valid_stop_is_rejected():
    e=RiskManagementEngine()
    pos={"ADAUSDT":{"entry_price":1.0,"quantity":1000,"stop_loss_price":None}}
    result=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions=pos,symbol="BTCUSDT",config={"cooldown_seconds":0},now_ms=DAY_MS)
    assert result["open_positions_missing_stop"]==1
    assert "OPEN_POSITION_WITHOUT_VALID_STOP_LOSS" in result["blockers"]

def test_phase_e_manual_order_actual_risk_and_exposure_limits():
    e=RiskManagementEngine()
    gate=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions={},symbol="BTCUSDT",
        config={"risk_per_trade_pct":0.5,"max_total_exposure_pct":10,"max_total_open_risk_pct":2,"cooldown_seconds":0},
        proposed_trade_risk_cash=60,proposed_notional=11000,now_ms=DAY_MS)
    assert "PROPOSED_TRADE_RISK_EXCEEDS_PER_TRADE_LIMIT" in gate["blockers"]
    assert "TOTAL_EXPOSURE_LIMIT_WOULD_BE_EXCEEDED" in gate["blockers"]

def test_phase_e_manual_order_actual_risk_passes_when_within_limits():
    e=RiskManagementEngine()
    gate=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions={},symbol="BTCUSDT",
        config={"risk_per_trade_pct":0.5,"max_total_exposure_pct":25,"max_total_open_risk_pct":3,"cooldown_seconds":0},
        proposed_trade_risk_cash=25,proposed_notional=2000,now_ms=DAY_MS)
    assert gate["allowed"] is True

def test_phase_e_manual_order_configured_leverage_cap():
    e=RiskManagementEngine()
    result=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions={},symbol="BTCUSDT",
        config={"risk_per_trade_pct":1,"max_leverage":2,"max_total_exposure_pct":25,"max_total_open_risk_pct":3,"cooldown_seconds":0},
        proposed_trade_risk_cash=20,proposed_notional=2000,proposed_leverage=3,now_ms=DAY_MS)
    assert "PROPOSED_LEVERAGE_EXCEEDS_CONFIGURED_LIMIT" in result["blockers"]

def test_phase_e_position_notional_cap_is_separate_from_portfolio_exposure():
    e=RiskManagementEngine()
    sizing=e.calculate({"account_equity":10000,"entry_price":100,"stop_loss_price":99.5,"side":"long",
        "risk_per_trade_pct":1,"leverage":1,"max_position_notional_pct":10})
    assert sizing["position_notional"]==1000
    assert sizing["position_limited_by_notional_cap"] is True

def test_phase_e_invalid_direction_stop_loss_is_treated_as_unprotected():
    e=RiskManagementEngine()
    positions={"XRPUSDT":{"side":"long","entry_price":100,"stop_loss_price":105,"quantity":1}}
    result=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions=positions,symbol="BTCUSDT",config={"cooldown_seconds":0},now_ms=DAY_MS)
    assert result["open_positions_missing_stop"]==1
    assert "OPEN_POSITION_WITHOUT_VALID_STOP_LOSS" in result["blockers"]

def test_phase_e_single_position_notional_limit_is_enforced():
    e=RiskManagementEngine()
    result=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions={},symbol="BTCUSDT",
        config={"risk_per_trade_pct":1,"max_position_notional_pct":10,"max_total_exposure_pct":25,"max_total_open_risk_pct":3,"cooldown_seconds":0},
        proposed_trade_risk_cash=20,proposed_notional=2000,proposed_leverage=1,now_ms=DAY_MS)
    assert "PROPOSED_POSITION_NOTIONAL_EXCEEDS_SINGLE_POSITION_LIMIT" in result["blockers"]
    assert "TOTAL_EXPOSURE_LIMIT_WOULD_BE_EXCEEDED" not in result["blockers"]

def test_phase_e_daily_loss_limit_does_not_expand_after_profit():
    e=RiskManagementEngine()
    result=e.evaluate_runtime_gate(account_equity=12000,closed_trades=[],orders=[],positions={},symbol="BTCUSDT",
        config={"max_daily_loss_pct":2,"cooldown_seconds":0},risk_limit_basis_equity=10000,now_ms=DAY_MS)
    assert result["risk_limit_basis_equity"]==10000
    assert result["daily_loss_limit"]==200

def test_phase_e_position_sizing_includes_entry_and_stop_exit_fees():
    e=RiskManagementEngine()
    result=e.calculate({"account_equity":10000,"entry_price":100,"stop_loss_price":90,"side":"long",
        "risk_per_trade_pct":1,"leverage":1,"fee_rate":0.001})
    assert result["estimated_loss_at_stop"]<=result["risk_budget"]
    assert result["estimated_fees_at_stop"]>0
    assert result["position_quantity"]<10
