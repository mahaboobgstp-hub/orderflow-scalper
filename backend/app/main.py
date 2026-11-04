from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.market_data.binance_stream import BinanceOrderBookStream


# --------------------------------------------------
# Market Data Engine
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Start the market data engine when FastAPI starts.
    Stop it gracefully when FastAPI shuts down.
    """

    market_stream = BinanceOrderBookStream(
        symbol="BTCUSDT"
    )

    app.state.market_stream = market_stream

    await market_stream.start()

    try:
        yield
    finally:
        await market_stream.stop()


# --------------------------------------------------
# FastAPI Application
# --------------------------------------------------

app = FastAPI(
    title="OrderFlow Scalper API",
    description="Market data and trading research backend",
    version="0.1.0",
    lifespan=lifespan,
)


# --------------------------------------------------
# Basic Health Check
# --------------------------------------------------

@app.get("/")
async def root():
    return {
        "application": "OrderFlow Scalper",
        "status": "running",
        "mode": "DEMO_DATA",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "FastAPI",
    }


# --------------------------------------------------
# Market Data Endpoints
# --------------------------------------------------

@app.get("/api/market-data/status")
async def market_data_status():
    """
    Check whether the market data stream is connected.
    """

    stream = app.state.market_stream

    return await stream.get_status()


@app.get("/api/market-data/order-book")
async def get_order_book():
    """
    Return the current local BTCUSDT order book.
    """

    stream = app.state.market_stream

    order_book = await stream.get_order_book()

    if not order_book:
        raise HTTPException(
            status_code=503,
            detail="Order book is not synchronized yet.",
        )

    return {
        "symbol": "BTCUSDT",
        "order_book": order_book,
    }
