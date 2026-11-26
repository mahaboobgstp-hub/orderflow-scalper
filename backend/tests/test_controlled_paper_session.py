import pytest
from app.services.controlled_paper_session import ControlledPaperSession

def active_session(**overrides):
    config={"enabled":True,"max_trades":3,"max_open_positions":2,"max_session_loss_pct":2,
            "max_session_minutes":60,"max_single_trade_risk_pct":0.5,"max_leverage":3}
    config.update(overrides)
    s=ControlledPaperSession(config)
    s.start(10000,now=1000)
    return s

def test_controller_disabled_by_default_blocks_entries():
    s=ControlledPaperSession({"enabled":False})
    assert s.state=="DISABLED"
    assert not s.entry_gate("buy",True)[0]

def test_active_session_status_is_paper_only():
    status=active_session().status()
    assert status["state"]=="ACTIVE" and status["mode"]=="PAPER_ONLY"
    assert status["live_exchange_orders"] is False

def test_pause_resume_stop_lifecycle():
    s=active_session(); s.pause("manual")
    assert not s.entry_gate("buy",True)[0]
    s.resume(); assert s.state=="ACTIVE"
    s.stop(); assert not s.entry_gate("buy",True)[0]

def test_synchronized_book_required():
    allowed,blockers=active_session().entry_gate("buy",False)
    assert not allowed and "BOOK_SYNC_REQUIRED" in blockers

def test_direction_permissions():
    s=active_session(allow_long=False,allow_short=True)
    assert not s.entry_gate("buy",True)[0]
    assert s.entry_gate("sell",True)[0]

def test_session_open_position_cap():
    s=active_session(max_open_positions=2)
    allowed,blockers=s.entry_gate("buy",True,open_positions=2)
    assert not allowed and "SESSION_MAX_OPEN_POSITIONS_REACHED" in blockers
    assert s.entry_gate("buy",True,open_positions=1)[0]

def test_trade_limit_auto_pauses():
    s=active_session(max_trades=2)
    s.record_entry("BTCUSDT","long"); s.record_entry("ETHUSDT","short")
    assert s.state=="PAUSED"
    assert "SESSION_TRADE_LIMIT_REACHED" in s.entry_gate("buy",True)[1]

def test_loss_limit_auto_pauses():
    s=active_session(max_session_loss_pct=1)
    allowed,blockers=s.entry_gate("buy",True,current_equity=9899)
    assert not allowed and s.state=="PAUSED"
    assert "SESSION_LOSS_LIMIT_REACHED" in blockers

def test_duration_auto_pauses(monkeypatch):
    s=active_session(max_session_minutes=1)
    monkeypatch.setattr("app.services.controlled_paper_session.time.time",lambda:1061)
    allowed,blockers=s.entry_gate("buy",True)
    assert not allowed and s.state=="PAUSED"
    assert "SESSION_TIME_LIMIT_REACHED" in blockers

def test_entry_exit_metrics():
    s=active_session()
    s.record_entry("BTCUSDT","long")
    s.record_exit({"symbol":"BTCUSDT","net_pnl":12.5,"close_reason":"TRAILING_TAKE_PROFIT"})
    s.record_exit({"symbol":"ETHUSDT","net_pnl":-4.0,"close_reason":"STOP_LOSS"})
    status=s.status()
    assert status["trades_started"]==1 and status["closed_trades"]==2
    assert status["wins"]==1 and status["losses"]==1 and status["realized_pnl"]==8.5

def test_config_limits_are_clamped():
    s=ControlledPaperSession({"enabled":True,"max_trades":5000,"max_open_positions":100,"max_leverage":50})
    assert s.config_values["max_trades"]==1000
    assert s.config_values["max_open_positions"]==20 and s.config_values["max_leverage"]==5
