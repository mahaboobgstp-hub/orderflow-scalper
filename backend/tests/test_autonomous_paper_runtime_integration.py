import asyncio
from app.services.autonomous_paper_runtime import AutonomousPaperRuntime
from app.services.controlled_paper_session import ControlledPaperSession
from app.services.nine_layer_decision_engine import NineLayerDecisionEngine
from app.services.paper_trading import PaperTradingEngine
from app.services.risk_management import RiskManagementEngine

class MarketData:
    def get_book(self, exchange, symbol):
        return {"synchronized":True,"stale":False,"integrity_error":False,"bids":[[99,10]],"asks":[[101,10]]}
    def get_recent_trades(self, exchange, symbol, limit):
        return [{"price":100,"quantity":1,"side":"buy"} for _ in range(20)]

class Detector:
    def __init__(self, output): self.output=output
    def analyze(self,*args): return self.output

def build_runtime(session):
    flow={"metrics":{"delta_ratio":0.9,"price_move_pct":0.5,"momentum_activity":"ACCELERATING"},"trade_count":40}
    return AutonomousPaperRuntime(
        scanner=None,paper_engine=PaperTradingEngine(10000),
        config={"max_open_positions":3,"max_daily_loss_pct":2,"max_consecutive_losses":3,
                "risk_per_trade_pct":0.5,"max_total_exposure_pct":25,"max_leverage":3,
                "initial_stop_loss_pct":1,"trailing_stop_enabled":True,"trailing_stop_pct":1,
                "trailing_take_profit_enabled":True,"trailing_take_profit_activation_pct":1,
                "trailing_take_profit_pct":0.5},
        watchlist=["BTCUSDT"],market_data=MarketData(),
        imbalance=Detector({"metrics":{"weighted_imbalance":0.9},"quality":{"score":90}}),
        absorption=Detector({"metrics":{"buy_absorption_score":0,"sell_absorption_score":0.8},"quality":{"score":90}}),
        zones=Detector({"zones":[{"interaction_state":"BREAKOUT_UP","zone_price":100}]}),
        trade_flow=Detector(flow),risk_engine=RiskManagementEngine(),
        decision_engine=NineLayerDecisionEngine({"decision_score_threshold":55}),
        validation_session=session)

def market_fixture():
    return {"symbol":"BTCUSDT","last_price":100,"spread_pct":0.02,"quote_volume_24h":50_000_000,
            "range_24h_pct":3,"price_change_24h_pct":25,"suitability_score":90}

def test_runtime_inactive_controlled_session_never_paper_executes():
    s=ControlledPaperSession({"enabled":True})
    runtime=build_runtime(s)
    result=runtime._evaluate_symbol(market_fixture(),{"score":40,"confidence":70,"reasons":["synthetic"]})
    assert result["decision"]=="BUY"
    assert result["paper_execution"]["status"]=="NOT_EXECUTED"
    assert runtime.paper_engine.account()["open_position_count"]==0

def test_runtime_active_controlled_session_paper_executes_only():
    s=ControlledPaperSession({"enabled":True,"max_open_positions":2,"max_trades":5})
    s.start(10000,now=__import__('time').time())
    runtime=build_runtime(s)
    result=runtime._evaluate_symbol(market_fixture(),{"score":40,"confidence":70,"reasons":["synthetic"]})
    assert result["decision"]=="BUY"
    assert result["paper_execution"]["status"]=="SIMULATED_OPEN"
    account=runtime.paper_engine.account()
    assert account["open_position_count"]==1
    assert runtime.paper_engine.orders[-1]["status"]=="FILLED_SIMULATED"
    assert s.trades_started==1
    assert runtime.status()["automatic_exchange_order_execution"] is False

def test_session_position_cap_blocks_runtime_paper_execution():
    s=ControlledPaperSession({"enabled":True,"max_open_positions":1})
    s.start(10000,now=1000)
    runtime=build_runtime(s)
    runtime.paper_engine.submit({"symbol":"ETHUSDT","side":"long","quantity":1,"price":100})
    result=runtime._evaluate_symbol(market_fixture(),{"score":40,"confidence":70,"reasons":["synthetic"]})
    assert result["paper_execution"]["status"]=="NOT_EXECUTED"
    assert "SESSION_MAX_OPEN_POSITIONS_REACHED" in result["controlled_session_gate"]["blockers"]
    assert runtime.paper_engine.account()["open_position_count"]==1

class TraceRepository:
    def __init__(self, fail_first_decision=False):
        self.decision_calls = 0
        self.signal_calls = 0
        self.fail_first_decision = fail_first_decision

    async def decision(self, symbol, decision, **kwargs):
        self.decision_calls += 1
        if self.fail_first_decision and self.decision_calls == 1:
            raise RuntimeError("temporary insert failure")
        return [{"id": f"decision-{self.decision_calls}"}]

    async def signal(self, symbol, side, signal_type, **kwargs):
        self.signal_calls += 1
        return [{"id": f"signal-{self.signal_calls}"}]


def trace_runtime(repository):
    return AutonomousPaperRuntime(scanner=None, paper_engine=PaperTradingEngine(10000),
        config={}, watchlist=[], repository=repository)


def trace_decision():
    return {"symbol":"BTCUSDT","decision":"BUY","side":"BUY","score":82,
        "consensus_ratio":0.9,"layers":{},"paper_execution":{"status":"SIMULATED_OPEN"}}


def test_runtime_trace_exposes_persistence_record_ids_and_deduplicates():
    repository = TraceRepository()
    runtime = trace_runtime(repository)
    first = trace_decision()
    asyncio.run(runtime._persist_decision(first))
    assert first["decision_persistence"] == {"status":"PERSISTED","record_id":"decision-1"}
    assert first["signal_persistence"] == {"status":"PERSISTED","record_id":"signal-1"}

    second = trace_decision()
    asyncio.run(runtime._persist_decision(second))
    assert second["decision_persistence"] == {"status":"UNCHANGED","record_id":"decision-1"}
    assert second["signal_persistence"] == {"status":"UNCHANGED","record_id":"signal-1"}
    assert repository.decision_calls == 1
    assert repository.signal_calls == 1


def test_runtime_retries_failed_decision_persistence_without_falsely_caching():
    repository = TraceRepository(fail_first_decision=True)
    runtime = trace_runtime(repository)
    first = trace_decision()
    asyncio.run(runtime._persist_decision(first))
    assert first["decision_persistence"]["status"] == "ERROR"
    assert first["decision_persistence"]["record_id"] is None

    second = trace_decision()
    asyncio.run(runtime._persist_decision(second))
    assert second["decision_persistence"] == {"status":"PERSISTED","record_id":"decision-2"}
    assert repository.decision_calls == 2
