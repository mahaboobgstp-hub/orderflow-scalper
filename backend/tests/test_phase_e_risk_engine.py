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
    assert "DAILY_LOSS_LIMIT_REACHED" in r["blockers"]]

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
    e=RiskManagementEngine(); pos={"ETHUSDT":{"entry_price":100,"stop_loss_price":95,"quantity":2}}
    r=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions=pos,symbol="BTCUSDT",config={"risk_per_trade_pct":0.5,"max_total_open_risk_pct":0.1,"cooldown_seconds":0},synchronized_book=False,now_ms=DAY_MS)
    assert r["open_stop_risk"]==10
    assert "SYNCHRONIZED_BOOK_UNAVAILABLE" in r["blockers"] and "TOTAL_OPEN_RISK_LIMIT_WOULD_BE_EXCEEDED" in r["blockers"]

def test_phase_e_position_without_valid_stop_is_rejected():
    e=RiskManagementEngine()
    pos={"ADAUSDT":{"entry_price":1.0,"quantity":1000,"stop_loss_price":None}}
    result=e.evaluate_runtime_gate(account_equity=10000,closed_trades=[],orders=[],positions=pos,symbol="BTCUSDT",config={"cooldown_seconds":0},now_ms=DAY_MS)
    assert result["open_positions_missing_stop"]==1
    assert "OPEN_POSITION_WITHOUT_VALID_STOP_LOSS" in result["blockers"]"
