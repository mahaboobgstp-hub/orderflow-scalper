import pytest
from fastapi import HTTPException
from app.main import app, paper_submit_order, PaperOrderRequest
from app.services.risk_management import RiskManagementEngine
from app.services.paper_trading import PaperTradingEngine

@pytest.mark.anyio
async def test_phase_e_emergency_halt_blocks_manual_paper_order():
    old_risk=getattr(app.state,"risk_management_engine",None)
    old_paper=getattr(app.state,"paper_trading_engine",None)
    risk=RiskManagementEngine(); risk.set_kill_switch(True,"test halt")
    app.state.risk_management_engine=risk
    app.state.paper_trading_engine=PaperTradingEngine(10000)
    try:
        request=PaperOrderRequest(symbol="BTCUSDT",side="long",quantity=0.01,price=50000,stop_loss_price=49000)
        with pytest.raises(HTTPException) as exc:
            await paper_submit_order(request)
        assert exc.value.status_code==423
        assert app.state.paper_trading_engine.account()["open_position_count"]==0
    finally:
        if old_risk is None: delattr(app.state,"risk_management_engine")
        else: app.state.risk_management_engine=old_risk
        if old_paper is None: delattr(app.state,"paper_trading_engine")
        else: app.state.paper_trading_engine=old_paper

@pytest.mark.anyio
async def test_phase_e_manual_paper_order_allowed_when_halt_clear():
    old_risk=getattr(app.state,"risk_management_engine",None)
    old_paper=getattr(app.state,"paper_trading_engine",None)
    app.state.risk_management_engine=RiskManagementEngine()
    app.state.paper_trading_engine=PaperTradingEngine(10000)
    try:
        request=PaperOrderRequest(symbol="BTCUSDT",side="long",quantity=0.01,price=50000,stop_loss_price=49000)
        result=await paper_submit_order(request)
        assert result["order"]["status"]=="FILLED_SIMULATED"
        assert app.state.paper_trading_engine.account()["open_position_count"]==1
    finally:
        if old_risk is None: delattr(app.state,"risk_management_engine")
        else: app.state.risk_management_engine=old_risk
        if old_paper is None: delattr(app.state,"paper_trading_engine")
        else: app.state.paper_trading_engine=old_paper

@pytest.mark.anyio
async def test_phase_e_manual_entry_requires_stop_loss():
    old_risk=getattr(app.state,"risk_management_engine",None); old_paper=getattr(app.state,"paper_trading_engine",None)
    app.state.risk_management_engine=RiskManagementEngine(); app.state.paper_trading_engine=PaperTradingEngine(10000)
    try:
        request=PaperOrderRequest(symbol="BTCUSDT",side="long",quantity=0.01,price=50000)
        with pytest.raises(HTTPException) as exc: await paper_submit_order(request)
        assert exc.value.status_code==422
    finally:
        if old_risk is None: delattr(app.state,"risk_management_engine")
        else: app.state.risk_management_engine=old_risk
        if old_paper is None: delattr(app.state,"paper_trading_engine")
        else: app.state.paper_trading_engine=old_paper

@pytest.mark.anyio
async def test_phase_e_manual_entry_rejects_excess_trade_risk():
    old_risk=getattr(app.state,"risk_management_engine",None); old_paper=getattr(app.state,"paper_trading_engine",None)
    app.state.risk_management_engine=RiskManagementEngine(); app.state.paper_trading_engine=PaperTradingEngine(10000)
    try:
        request=PaperOrderRequest(symbol="BTCUSDT",side="long",quantity=0.01,price=50000,stop_loss_price=40000)
        with pytest.raises(HTTPException) as exc: await paper_submit_order(request)
        assert exc.value.status_code==409
        assert "PROPOSED_TRADE_RISK_EXCEEDS_PER_TRADE_LIMIT" in exc.value.detail["blockers"]
    finally:
        if old_risk is None: delattr(app.state,"risk_management_engine")
        else: app.state.risk_management_engine=old_risk
        if old_paper is None: delattr(app.state,"paper_trading_engine")
        else: app.state.paper_trading_engine=old_paper

@pytest.mark.anyio
async def test_phase_e_manual_entry_rejects_portfolio_exposure_over_cap():
    old_risk=getattr(app.state,"risk_management_engine",None); old_paper=getattr(app.state,"paper_trading_engine",None)
    app.state.risk_management_engine=RiskManagementEngine(); app.state.paper_trading_engine=PaperTradingEngine(10000)
    try:
        request=PaperOrderRequest(symbol="BTCUSDT",side="long",quantity=0.06,price=50000,stop_loss_price=49900)
        with pytest.raises(HTTPException) as exc: await paper_submit_order(request)
        assert exc.value.status_code==409
        assert "TOTAL_EXPOSURE_LIMIT_WOULD_BE_EXCEEDED" in exc.value.detail["blockers"]
    finally:
        if old_risk is None: delattr(app.state,"risk_management_engine")
        else: app.state.risk_management_engine=old_risk
        if old_paper is None: delattr(app.state,"paper_trading_engine")
        else: app.state.paper_trading_engine=old_paper

@pytest.mark.anyio
async def test_phase_e_emergency_halt_keeps_runtime_running_for_position_management(monkeypatch):
    from app.services import operator_control
    old_runtime=operator_control.runtime
    old_engine_state=operator_control.state["engine_state"]
    old_events=list(operator_control.state["events"])
    old_updated=operator_control.state["updated_at"]
    risk=RiskManagementEngine()
    class RuntimeStub:
        def __init__(self):
            self.risk_engine=risk; self.stop_called=False
        def status(self): return {"state":"RUNNING"}
        async def stop(self): self.stop_called=True
    stub=RuntimeStub()
    operator_control.set_runtime(stub)
    monkeypatch.setenv("CONTROL_API_TOKEN","test-control-token")
    try:
        response=await operator_control.engine_command(operator_control.EngineCommandRequest(command="EMERGENCY_HALT"),"test-control-token")
        assert response["applied"] is True
        assert response["engine_state"]=="RUNNING"
        assert risk.kill_switch_status()["active"] is True
        assert stub.stop_called is False
    finally:
        operator_control.set_runtime(old_runtime)
        operator_control.state["engine_state"]=old_engine_state
        operator_control.state["events"]=old_events
        operator_control.state["updated_at"]=old_updated

@pytest.mark.anyio
async def test_phase_e_kill_switch_reset_persists_before_clearing(monkeypatch):
    from app.services import operator_control
    old_runtime=operator_control.runtime; old_state=operator_control.state["engine_state"]
    old_events=list(operator_control.state["events"]); old_updated=operator_control.state["updated_at"]
    risk=RiskManagementEngine(); risk.set_kill_switch(True,"persisted test halt")
    class RepoStub:
        def __init__(self): self.calls=[]
        async def engine_state(self,**kwargs): self.calls.append(kwargs); return True
    class RuntimeStub:
        def __init__(self): self.risk_engine=risk; self.repository=RepoStub()
        def status(self): return {"state":"STOPPED"}
    stub=RuntimeStub(); operator_control.set_runtime(stub)
    monkeypatch.setenv("CONTROL_API_TOKEN","test-control-token")
    try:
        response=await operator_control.reset_risk_kill_switch("test-control-token")
        assert response["reset"] is True and response["persisted"] is True
        assert risk.kill_switch_status()["active"] is False
        assert stub.repository.calls[-1]["state"]["risk_kill_switch"]["active"] is False
    finally:
        operator_control.set_runtime(old_runtime); operator_control.state["engine_state"]=old_state
        operator_control.state["events"]=old_events; operator_control.state["updated_at"]=old_updated

@pytest.mark.anyio
async def test_phase_e_kill_switch_reset_fails_closed_on_persistence_failure(monkeypatch):
    from app.services import operator_control
    old_runtime=operator_control.runtime; old_state=operator_control.state["engine_state"]
    old_events=list(operator_control.state["events"]); old_updated=operator_control.state["updated_at"]
    risk=RiskManagementEngine(); risk.set_kill_switch(True,"persist failure test")
    class RepoStub:
        async def engine_state(self,**kwargs): return False
    class RuntimeStub:
        def __init__(self): self.risk_engine=risk; self.repository=RepoStub()
        def status(self): return {"state":"STOPPED"}
    operator_control.set_runtime(RuntimeStub())
    monkeypatch.setenv("CONTROL_API_TOKEN","test-control-token")
    try:
        with pytest.raises(HTTPException) as exc: await operator_control.reset_risk_kill_switch("test-control-token")
        assert exc.value.status_code==503
        assert risk.kill_switch_status()["active"] is True
    finally:
        operator_control.set_runtime(old_runtime); operator_control.state["engine_state"]=old_state
        operator_control.state["events"]=old_events; operator_control.state["updated_at"]=old_updated

@pytest.mark.anyio
async def test_phase_e_persistence_worker_restores_halt_state():
    from app.services.paper_persistence import PaperPersistenceWorker
    class RepoStub:
        async def load_paper_state(self):
            return {"snapshot":{"risk_kill_switch":{"active":True,"reason":"persisted emergency"},"paper_account":{}},
                    "open_positions":[]}
    worker=PaperPersistenceWorker(repo=RepoStub())
    engine=PaperTradingEngine(10000)
    await worker.restore_state(engine)
    assert worker.risk_control_state["active"] is True
    assert worker.risk_control_state["reason"]=="persisted emergency"

@pytest.mark.anyio
async def test_phase_e_state_recovery_failure_activates_fail_closed_halt():
    from app.services.paper_persistence import PaperPersistenceWorker
    class RepoStub:
        async def load_paper_state(self): raise RuntimeError("storage unavailable")
    worker=PaperPersistenceWorker(repo=RepoStub())
    engine=PaperTradingEngine(10000)
    await worker.restore_state(engine)
    assert worker.risk_control_state["active"] is True
    assert worker.risk_control_state["reason"]=="RISK_CONTROL_STATE_UNAVAILABLE"
