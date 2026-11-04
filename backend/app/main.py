from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.market_data.backend_stream import BinanceOrderBookStream


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Start the market-data stream with FastAPI.
    Stop it cleanly when FastAPI shuts down.
    """

    stream = BinanceOrderBookStream(symbol="BTCUSDT")
    app.state.market_stream = stream

    await stream.start()

    try:
        yield
    finally:
        await stream.stop()


app = FastAPI(
    title="OrderFlow Scalper API",
    description="Market data and trading research backend",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    return {
        "application": "OrderFlow Scalper",
        "status": "running",
        "mode": "DEMO_MARKET_DATA",
        "trading_mode": "PAPER_ONLY",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "FastAPI",
        "trading_mode": "PAPER_ONLY",
    }


@app.get("/api/market-data/status")
async def market_data_status():
    stream = app.state.market_stream
    return await stream.get_status()


@app.get("/api/market-data/order-book")
async def get_order_book():
    stream = app.state.market_stream
    order_book = await stream.get_order_book()

    if order_book is None:
        raise HTTPException(
            status_code=503,
            detail="Order book is not synchronized yet.",
        )

    return {
        "symbol": "BTCUSDT",
        "order_book": order_book,
    }
