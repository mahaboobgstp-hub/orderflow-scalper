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
