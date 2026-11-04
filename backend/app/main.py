from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.execution.binance_demo_client import (
    BinanceDemoClient,
    BinanceDemoError,
)
from app.execution.order_service import (
    DemoOrderService,
    OrderRejected,
)
from app.market_data.backend_stream import BinanceOrderBookStream


@asynccontextmanager
async def lifespan(app: FastAPI):
    stream = BinanceOrderBookStream(symbol="BTCUSDT")
    app.state.market_stream = stream

    await stream.start()

    try:
        yield
    finally:
        await stream.stop()


app = FastAPI(
    title="OrderFlow Scalper API",
    description="Binance Demo market data and demo execution backend",
    version="0.2.0",
    lifespan=lifespan,
)


class DemoOrderRequest(BaseModel):
    symbol: str = Field(default="BTCUSDT", min_length=3, max_length=20)
    side: str
    quantity: float = Field(gt=0)


@app.get("/")
async def root():
    return {
        "application": "OrderFlow Scalper",
        "status": "running",
        "mode": "BINANCE_FUTURES_DEMO",
        "demo_execution_enabled": settings.execution_enabled,
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "FastAPI",
        "mode": "BINANCE_FUTURES_DEMO",
        "demo_execution_enabled": settings.execution_enabled,
    }


@app.get("/api/market-data/status")
async def market_data_status():
    return await app.state.market_stream.get_status()


@app.get("/api/market-data/order-book")
async def get_order_book():
    order_book = await app.state.market_stream.get_order_book()

    if order_book is None:
        raise HTTPException(
            status_code=503,
            detail="Order book is not synchronized yet.",
        )

    return {
        "symbol": "BTCUSDT",
        "order_book": order_book,
    }


@app.get("/api/demo/account")
async def demo_account():
    try:
        return await BinanceDemoClient().get_account()
    except BinanceDemoError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/api/demo/orders")
async def place_demo_order(request: DemoOrderRequest):
    try:
        result = await DemoOrderService().place_market_order(
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
        )
        return {
            "mode": "BINANCE_FUTURES_DEMO",
            "order": result,
        }
    except OrderRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except BinanceDemoError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
