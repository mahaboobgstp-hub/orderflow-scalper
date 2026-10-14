from datetime import datetime, timezone
from collections import deque
from threading import Lock

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="OrderFlow Scalper",
    description="Order-book research and paper-trading API",
    version="0.2.0",
)

# Temporary in-memory history: keeps the latest 500 snapshots.
snapshot_history = deque(maxlen=500)
history_lock = Lock()


class MarketSnapshot(BaseModel):
    symbol: str = "IDFCFIRSTB"
    last_price: float = Field(gt=0)
    bid_price: float = Field(gt=0)
    ask_price: float = Field(gt=0)
    bid_quantity: int = Field(ge=0)
    ask_quantity: int = Field(ge=0)


def analyse_snapshot(snapshot: MarketSnapshot):
    total = snapshot.bid_quantity + snapshot.ask_quantity

    imbalance = (
        (snapshot.bid_quantity - snapshot.ask_quantity) / total
        if total > 0
        else 0.0
    )

    spread = round(snapshot.ask_price - snapshot.bid_price, 4)

    if imbalance > 0.20:
        interpretation = "More displayed bid quantity"
    elif imbalance < -0.20:
        interpretation = "More displayed offer quantity"
    else:
        interpretation = "Displayed quantities are relatively balanced"

    return {
        "symbol": snapshot.symbol,
        "last_price": snapshot.last_price,
        "bid_price": snapshot.bid_price,
        "ask_price": snapshot.ask_price,
        "bid_quantity": snapshot.bid_quantity,
        "ask_quantity": snapshot.ask_quantity,
        "spread": spread,
        "book_imbalance": round(imbalance, 4),
        "interpretation": interpretation,
        "trade_action": "NONE",
        "mode": "PAPER_ONLY",
    }


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
    result = analyse_snapshot(snapshot)
    result["timestamp"] = datetime.now(timezone.utc).isoformat()

    with history_lock:
        snapshot_history.append(result.copy())

    return result


@app.get("/api/history")
def get_history(limit: int = 50):
    limit = max(1, min(limit, 500))

    with history_lock:
        records = list(snapshot_history)[-limit:]
        records.reverse()

    return {
        "count": len(records),
        "max_records": 500,
        "mode": "PAPER_ONLY",
        "history": records,
    }


@app.delete("/api/history")
def clear_history():
    with history_lock:
        snapshot_history.clear()

    return {
        "message": "Snapshot history cleared",
        "count": 0,
        "mode": "PAPER_ONLY",
    }
