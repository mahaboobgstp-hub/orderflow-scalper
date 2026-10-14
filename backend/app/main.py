
from datetime import datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="OrderFlow Scalper",
    description="Order-book research and paper-trading API",
    version="0.1.0",
)


class MarketSnapshot(BaseModel):
    symbol: str = "IDFCFIRSTB"
    last_price: float = Field(gt=0)
    bid_price: float = Field(gt=0)
    ask_price: float = Field(gt=0)
    bid_quantity: int = Field(ge=0)
    ask_quantity: int = Field(ge=0)


@app.get("/")
def home():
    return {
        "app": "OrderFlow Scalper",
        "mode": "PAPER_ONLY",
        "message": "Backend is running",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/analyse")
def analyse(snapshot: MarketSnapshot):
    total = snapshot.bid_quantity + snapshot.ask_quantity

    imbalance = (
        (snapshot.bid_quantity - snapshot.ask_quantity) / total
        if total > 0
        else 0.0
    )

    spread = round(snapshot.ask_price - snapshot.bid_price, 4)

    # A research indicator only—not a trading recommendation.
    if imbalance > 0.20:
        interpretation = "More displayed bid quantity"
    elif imbalance < -0.20:
        interpretation = "More displayed offer quantity"
    else:
        interpretation = "Displayed quantities are relatively balanced"

    return {
        "symbol": snapshot.symbol,
        "last_price": snapshot.last_price,
        "spread": spread,
        "book_imbalance": round(imbalance, 4),
        "interpretation": interpretation,
        "trade_action": "NONE",
        "mode": "PAPER_ONLY",
    }
