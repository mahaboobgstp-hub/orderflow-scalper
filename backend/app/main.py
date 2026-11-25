from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    stream=BinanceOrderBookStream(symbol="BTCUSDT"); app.state.market_stream=stream
    engine=UnifiedMarketDataEngine(); app.state.unified_market_data=engine
    app.state.coin_scanner=CoinMarketScanner()
    app.state.imbalance_detector=OrderBookImbalanceDetector()
    app.state.absorption_detector=AbsorptionLiquidityDetector()
    app.state.liquidity_zone_detector=LiquidityZoneDetector()
    app.state.trade_flow_momentum_detector=TradeFlowMomentumDetector()
    callback=lambda exchange,payload: engine.process(exchange,payload)
    manager=ExchangeConnectionManager([
        BinancePublicAdapter(enabled=settings.binance_public_enabled,symbol="BTCUSDT",on_message=callback),
        BybitPublicAdapter(enabled=settings.bybit_public_enabled,symbol=settings.bybit_public_symbol,on_message=callback),
        DeltaPublicAdapter(enabled=settings.delta_public_enabled,symbol=settings.delta_public_symbol,on_message=callback),
    ])
    app.state.exchange_manager=manager
    await stream.start(); await manager.start()
    try: yield
    finally:
        await manager.stop(); await stream.stop()

app=FastAPI(title="OrderFlow Scalper API",description="Multi-exchange public market-data and Binance demo execution backend",version="0.5.0")

class DemoOrderRequest(BaseModel):
    symbol:str=Field(default="BTCUSDT",min_length=3,max_length=20)
    side:str
    quantity:float=Field(gt=0)

@app.get("/")
async def root():
    return {"application":"OrderFlow Scalper","status":"running","mode":"BINANCE_FUTURES_DEMO","demo_execution_enabled":settings.execution_enabled}
@app.get("/health")
async def health():
    return {"status":"ok","service":"FastAPI","mode":"BINANCE_FUTURES_DEMO","demo_execution_enabled":settings.execution_enabled}
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
