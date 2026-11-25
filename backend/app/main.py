from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any
from app.config import settings
from app.execution.binance_demo_client import BinanceDemoClient, BinanceDemoError
from app.execution.order_service import DemoOrderService, OrderRejected
from app.market_data.backend_stream import BinanceOrderBookStream
from app.market_data.unified_engine import UnifiedMarketDataEngine
from app.exchanges.manager import ExchangeConnectionManager, BinancePublicAdapter, BybitPublicAdapter, DeltaPublicAdapter
from app.services.coin_scanner import CoinMarketScanner
from app.services.imbalance_detector import OrderBookImbalanceDetector
from app.services.absorption_detector import AbsorptionLiquidityDetector
from app.services.liquidity_zone_detector import LiquidityZoneDetector
from app.services.trade_flow_momentum import TradeFlowMomentumDetector
from app.services.market_context_dummy_api import DummyMarketContextAPI
from app.services.market_regime_context import MarketRegimeContextEngine
from app.services.risk_management import RiskManagementEngine
from app.services.paper_trading import PaperTradingEngine
from app.services.backtesting import BacktestEngine
from app.services.monitoring import MonitoringService
from app.services.operator_control import router as operator_control_router, set_runtime, state as operator_control_state
from app.services.autonomous_paper_runtime import AutonomousPaperRuntime
import logging
import os
import time

logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO').upper(),format='%(asctime)s %(levelname)s %(name)s %(message)s')
logger=logging.getLogger('orderflow-scalper')

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.monitoring_service=MonitoringService()
    stream=BinanceOrderBookStream(symbol="BTCUSDT"); app.state.market_stream=stream
    engine=UnifiedMarketDataEngine(); app.state.unified_market_data=engine
    app.state.coin_scanner=CoinMarketScanner()
    app.state.imbalance_detector=OrderBookImbalanceDetector()
    app.state.absorption_detector=AbsorptionLiquidityDetector()
    app.state.liquidity_zone_detector=LiquidityZoneDetector()
    app.state.trade_flow_momentum_detector=TradeFlowMomentumDetector()
    app.state.market_context_dummy_api=DummyMarketContextAPI()
    app.state.market_regime_context_engine=MarketRegimeContextEngine()
    app.state.risk_management_engine=RiskManagementEngine()
    app.state.paper_trading_engine=PaperTradingEngine()
    app.state.backtesting_engine=BacktestEngine()
    runtime=AutonomousPaperRuntime(app.state.coin_scanner,app.state.paper_trading_engine,operator_control_state["config"],operator_control_state["watchlist"])
    set_runtime(runtime)
    callback=lambda exchange,payload: engine.process(exchange,payload)
    manager=ExchangeConnectionManager([
        BinancePublicAdapter(enabled=settings.binance_public_enabled,symbol="BTCUSDT",on_message=callback),
        BybitPublicAdapter(enabled=settings.bybit_public_enabled,symbol=settings.bybit_public_symbol,on_message=callback),
        DeltaPublicAdapter(enabled=settings.delta_public_enabled,symbol=settings.delta_public_symbol,on_message=callback),
    ])
    app.state.exchange_manager=manager
    try:
        await stream.start(); await manager.start()
        app.state.monitoring_service.record('INFO','startup_complete',{'exchange_adapters':3})
        yield
    except Exception as exc:
        app.state.monitoring_service.record('ERROR','startup_or_runtime_error',{'error_type':type(exc).__name__})
        logger.exception('Application lifecycle error')
        raise
    finally:
        try: await runtime.stop()
        except Exception: logger.exception("Autonomous runtime shutdown error")
        try: await manager.stop()
        except Exception: logger.exception('Exchange manager shutdown error')
        try: await stream.stop()
        except Exception: logger.exception('Market stream shutdown error')

app=FastAPI(title="OrderFlow Scalper API",description="Multi-exchange public market-data and Binance demo execution backend",version="0.5.0")
allowed_origins=[origin.strip() for origin in os.getenv("FRONTEND_ORIGINS","https://orderflow-scalper-ivory.vercel.app").split(",") if origin.strip()]
app.add_middleware(CORSMiddleware,allow_origins=allowed_origins,allow_methods=["GET","POST","PUT","OPTIONS"],allow_headers=["Content-Type","X-Control-Token"])
@app.middleware("http")
async def request_monitoring(request, call_next):
    started=time.perf_counter()
    try:
        response=await call_next(request)
        duration_ms=(time.perf_counter()-started)*1000
        if hasattr(app.state,"monitoring_service"):
            app.state.monitoring_service.record("ERROR" if response.status_code>=500 else "INFO","http_request",{"method":request.method,"path":request.url.path,"status_code":response.status_code,"duration_ms":round(duration_ms,2)})
        if response.status_code>=500: logger.error("HTTP %s %s returned %s",request.method,request.url.path,response.status_code)
        return response
    except Exception as exc:
        if hasattr(app.state,"monitoring_service"):
            app.state.monitoring_service.record("ERROR","request_exception",{"method":request.method,"path":request.url.path,"error_type":type(exc).__name__})
        logger.exception("Unhandled request exception")
        raise


class RiskSizingRequest(BaseModel):
    symbol:str=Field(default="UNKNOWN",min_length=1,max_length=30)
    account_equity:float=Field(gt=0)
    entry_price:float=Field(gt=0)
    stop_loss_price:float=Field(gt=0)
    side:str
    risk_per_trade_pct:float|None=Field(default=None,ge=0.01,le=5)
    leverage:float=Field(default=1.0,ge=1,le=5)
    max_position_notional_pct:float|None=Field(default=None,ge=1,le=100)
class PortfolioRiskRequest(BaseModel):
    account_equity:float=Field(gt=0)
    daily_realized_loss:float=Field(default=0,ge=0)
    open_risk:float=Field(default=0,ge=0)
    open_positions:int=Field(default=0,ge=0)
    consecutive_losses:int=Field(default=0,ge=0)
    risk_per_trade_pct:float|None=Field(default=None,ge=0.01,le=5)
class PaperOrderRequest(BaseModel):
    symbol:str=Field(min_length=1,max_length=30)
    side:str
    quantity:float=Field(gt=0)
    price:float=Field(gt=0)
    leverage:float=Field(default=1.0,ge=1,le=5)
    stop_loss_price:float|None=Field(default=None,gt=0)
    take_profit_price:float|None=Field(default=None,gt=0)
    tsl_enabled:bool=False
    tsl_distance_pct:float|None=Field(default=None,gt=0,lt=100)
    ttp_enabled:bool=False
    ttp_activation_pct:float|None=Field(default=None,gt=0,lt=100)
    ttp_trail_pct:float|None=Field(default=None,gt=0,lt=100)
class PaperManagementRequest(BaseModel):
    stop_loss_price:float|None=None
    take_profit_price:float|None=None
    tsl_enabled:bool|None=None
    tsl_distance_pct:float|None=None
    ttp_enabled:bool|None=None
    ttp_activation_pct:float|None=None
    ttp_trail_pct:float|None=None
class PaperMarkPriceRequest(BaseModel):
    symbol:str=Field(min_length=1,max_length=30)
    price:float=Field(gt=0)
class PaperCloseRequest(BaseModel):
    price:float=Field(gt=0)
class PaperResetRequest(BaseModel):
    initial_equity:float=Field(gt=0)
class BacktestCandle(BaseModel):
    timestamp: str | int | float | None = None
    open: float=Field(gt=0)
    high: float=Field(gt=0)
    low: float=Field(gt=0)
    close: float=Field(gt=0)
class BacktestRunRequest(BaseModel):
    candles:list[BacktestCandle]
    config:dict[str,Any]={}
class DemoOrderRequest(BaseModel):
    symbol:str=Field(default="BTCUSDT",min_length=3,max_length=20)
    side:str
    quantity:float=Field(gt=0)

@app.get("/")
async def root():
    return {"application":"OrderFlow Scalper","status":"running","mode":"BINANCE_FUTURES_DEMO","demo_execution_enabled":settings.execution_enabled}
@app.get("/health")
async def health():
    return app.state.monitoring_service.health()
@app.get("/api/monitoring/diagnostics")
async def monitoring_diagnostics():
    return app.state.monitoring_service.diagnostics(app)
@app.get("/api/monitoring/events")
async def monitoring_events(limit:int=Query(default=100,ge=1,le=500)):
    return app.state.monitoring_service.recent_events(limit)
@app.get("/api/exchanges/status")
async def exchange_connectivity_status(): return await app.state.exchange_manager.status()
@app.get("/api/market-data/status")
async def market_data_status(): return await app.state.market_stream.get_status()
@app.get("/api/market-data/order-book")
async def get_order_book():
    book=await app.state.market_stream.get_order_book()
    if book is None: raise HTTPException(status_code=503,detail="Order book is not synchronized yet.")
    return {"symbol":"BTCUSDT","order_book":book}
@app.get("/api/market-data/unified/status")
async def unified_status(): return app.state.unified_market_data.get_status()
@app.get("/api/market-data/unified/book/{exchange}/{symbol}")
async def unified_book(exchange:str,symbol:str):
    book=app.state.unified_market_data.get_book(exchange,symbol)
    if book is None: raise HTTPException(status_code=404,detail="No normalized book data available for this exchange/symbol.")
    return book
@app.get("/api/market-data/unified/trades/{exchange}/{symbol}")
async def unified_trades(exchange:str,symbol:str,limit:int=100):
    if exchange.lower() not in {"binance","bybit","delta"}: raise HTTPException(status_code=400,detail="Unsupported exchange.")
    return {"exchange":exchange.lower(),"symbol":symbol.upper(),"trades":app.state.unified_market_data.get_recent_trades(exchange,symbol,limit)}
@app.get("/api/imbalance/status")
async def imbalance_status():
    return app.state.imbalance_detector.status()
@app.get("/api/imbalance/{exchange}/{symbol}")
async def analyze_imbalance(exchange:str,symbol:str,levels:int=Query(default=10,ge=1,le=20)):
    if exchange.lower() not in {"binance","bybit","delta"}:
        raise HTTPException(status_code=400,detail="Unsupported exchange.")
    book=app.state.unified_market_data.get_book(exchange,symbol)
    if book is None:
        raise HTTPException(status_code=404,detail="No normalized book data available for this exchange/symbol.")
    try:
        return app.state.imbalance_detector.analyze(book,levels=levels)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc))
@app.get("/api/absorption/status")
async def absorption_status():
    return app.state.absorption_detector.status()
@app.get("/api/absorption/{exchange}/{symbol}")
async def analyze_absorption(exchange:str,symbol:str,lookback_seconds:float=Query(default=15.0,ge=1.0,le=120.0),limit:int=Query(default=500,ge=1,le=500)):
    if exchange.lower() not in {"binance","bybit","delta"}:
        raise HTTPException(status_code=400,detail="Unsupported exchange.")
    book=app.state.unified_market_data.get_book(exchange,symbol)
    if book is None:
        raise HTTPException(status_code=404,detail="No normalized order book available for this exchange/symbol.")
    trades=app.state.unified_market_data.get_recent_trades(exchange,symbol,limit)
    try:
        return app.state.absorption_detector.analyze(book,trades,lookback_seconds=lookback_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc))
@app.get("/api/liquidity-zones/status")
async def liquidity_zones_status():
    return app.state.liquidity_zone_detector.status()
@app.get("/api/liquidity-zones/{exchange}/{symbol}")
async def analyze_liquidity_zones(exchange:str,symbol:str,lookback_seconds:float=Query(default=300.0,ge=10.0,le=3600.0),limit:int=Query(default=500,ge=1,le=500)):
    if exchange.lower() not in {"binance","bybit","delta"}:
        raise HTTPException(status_code=400,detail="Unsupported exchange.")
    book=app.state.unified_market_data.get_book(exchange,symbol)
    if book is None:
        raise HTTPException(status_code=404,detail="No normalized order book available for this exchange/symbol.")
    trades=app.state.unified_market_data.get_recent_trades(exchange,symbol,limit)
    try:
        return app.state.liquidity_zone_detector.analyze(book,trades,lookback_seconds=lookback_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc))
@app.get("/api/trade-flow/status")
async def trade_flow_status():
    return app.state.trade_flow_momentum_detector.status()
@app.get("/api/trade-flow/{exchange}/{symbol}")
async def analyze_trade_flow(exchange:str,symbol:str,lookback_seconds:float=Query(default=15.0,ge=1.0,le=120.0),limit:int=Query(default=500,ge=1,le=500)):
    if exchange.lower() not in {"binance","bybit","delta"}:
        raise HTTPException(status_code=400,detail="Unsupported exchange.")
    book=app.state.unified_market_data.get_book(exchange,symbol)
    if book is None:
        raise HTTPException(status_code=404,detail="No normalized order book available for this exchange/symbol.")
    trades=app.state.unified_market_data.get_recent_trades(exchange,symbol,limit)
    try:
        return app.state.trade_flow_momentum_detector.analyze(book,trades,lookback_seconds=lookback_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=422,detail=str(exc))
@app.get("/api/scanner/coins")
async def scan_coins(limit:int=Query(default=20,ge=1,le=100),include_rejected:bool=False):
    """On-demand market scan. It calls public Binance USD-M endpoints."""
    try:
        return await app.state.coin_scanner.scan(limit=limit,include_rejected=include_rejected)
    except Exception as exc:
        raise HTTPException(status_code=502,detail=f"Coin scan failed: {exc}")
@app.get("/api/demo/account")
async def demo_account():
    try: return await BinanceDemoClient().get_account()
    except BinanceDemoError as exc: raise HTTPException(status_code=502,detail=str(exc))
@app.post("/api/demo/orders")
async def place_demo_order(request:DemoOrderRequest):
    try:
        result=await DemoOrderService().place_market_order(symbol=request.symbol,side=request.side,quantity=request.quantity)
        return {"mode":"BINANCE_FUTURES_DEMO","order":result}
    except OrderRejected as exc: raise HTTPException(status_code=400,detail=str(exc))
    except BinanceDemoError as exc: raise HTTPException(status_code=502,detail=str(exc))

# Phase 9 — Dummy market context endpoints (explicitly non-live)
@app.get("/api/market-context/status")
async def market_context_status():
    return {"phase":9,"provider":"dummy_ohlcv_api","data_mode":"DUMMY","is_live":False,"engine":"market_regime_context","message":"Dummy OHLCV API is enabled for integration testing. Replace provider with real exchange APIs later."}
@app.get("/api/market-context/candles/{symbol}")
async def market_context_candles(symbol:str,interval:str="1m",limit:int=Query(default=120,ge=40,le=500)):
    allowed={"1m","3m","5m","15m","1h"}
    if interval not in allowed: raise HTTPException(status_code=400,detail="Supported intervals: 1m, 3m, 5m, 15m, 1h")
    return app.state.market_context_dummy_api.get_candles(symbol,interval,limit)
@app.get("/api/market-context/regime/{symbol}")
async def market_context_regime(symbol:str,interval:str="1m",limit:int=Query(default=120,ge=40,le=500),fast_period:int=Query(default=12,ge=3,le=50),slow_period:int=Query(default=36,ge=4,le=200)):
    allowed={"1m","3m","5m","15m","1h"}
    if interval not in allowed: raise HTTPException(status_code=400,detail="Supported intervals: 1m, 3m, 5m, 15m, 1h")
    if slow_period<=fast_period: raise HTTPException(status_code=400,detail="slow_period must be greater than fast_period")
    payload=app.state.market_context_dummy_api.get_candles(symbol,interval,limit)
    try: return app.state.market_regime_context_engine.analyze(payload,fast_period,slow_period)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))

# Phase 10 risk-management endpoints — advisory/calculation only
@app.get("/api/risk/status")
async def risk_engine_status():
    return app.state.risk_management_engine.status()
@app.post("/api/risk/position-size")
async def risk_position_size(request:RiskSizingRequest):
    try: return app.state.risk_management_engine.calculate(request.model_dump())
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))
@app.post("/api/risk/portfolio-check")
async def risk_portfolio_check(request:PortfolioRiskRequest):
    try: return app.state.risk_management_engine.evaluate_portfolio(**request.model_dump())
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))

# Phase 13 — Offline historical backtesting (never fetches market data)
@app.get("/api/backtest/status")
async def backtest_status():
    return {"phase":13,"engine":"offline_backtesting","mode":"OFFLINE_HISTORICAL_CANDLES","data_is_live":False,"strategy":"EMA_CROSS baseline","exchange_api_calls":False,"metrics":["net_pnl","return_pct","win_rate","profit_factor","average_win","average_loss","max_drawdown","long_short_attribution"],"warning":"Candle-only baseline. Order-book strategy evaluation requires richer historical data and later integration."}
@app.post("/api/backtest/run")
async def run_backtest(request:BacktestRunRequest):
    try: return app.state.backtesting_engine.run([c.model_dump() for c in request.candles],request.config)
    except (ValueError,TypeError,KeyError) as exc: raise HTTPException(status_code=422,detail=str(exc))

# Phase 11 — Paper-only simulator endpoints; never call exchange execution
@app.get("/api/paper/status")
async def paper_status():
    return app.state.paper_trading_engine.status()
@app.get("/api/paper/account")
async def paper_account():
    return app.state.paper_trading_engine.account()
@app.post("/api/paper/orders")
async def paper_submit_order(request:PaperOrderRequest):
    try: return app.state.paper_trading_engine.submit(request.model_dump())
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))
@app.post("/api/paper/manage/{symbol}")
async def paper_manage_position(symbol:str,request:PaperManagementRequest):
    try: return app.state.paper_trading_engine.update_management(symbol,request.model_dump(exclude_unset=True))
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))
@app.post("/api/paper/mark-price")
async def paper_mark_price(request:PaperMarkPriceRequest):
    try: return app.state.paper_trading_engine.mark(request.symbol,request.price)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))
@app.post("/api/paper/close/{symbol}")
async def paper_close_position(symbol:str,request:PaperCloseRequest):
    try: return app.state.paper_trading_engine.close(symbol,request.price)
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc))
@app.get("/api/paper/history")
async def paper_history(limit:int=Query(default=100,ge=1,le=500)):
    return app.state.paper_trading_engine.history(limit)
@app.post("/api/paper/reset")
async def paper_reset(request:PaperResetRequest):
    return app.state.paper_trading_engine.reset(request.initial_equity)

# Operator controls (API-only state; autonomous engine integration is not yet enabled)
app.include_router(operator_control_router)