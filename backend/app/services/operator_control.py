"""Remote operator controls for OrderFlow Scalper. Config is in-memory only.
Autonomous strategy execution is not integrated; engine commands are safely blocked.
"""
from __future__ import annotations
import os
import time
import asyncio
from typing import Any
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/control", tags=["operator-control"])
runtime = None

def set_runtime(engine):
    global runtime
    runtime = engine
state: dict[str, Any] = {
    "engine_state": "STOPPED",
    "mode": "PAPER_ONLY",
    "config": {
        "risk_per_trade_pct": 0.5,
        "max_daily_loss_pct": 2.0,
        "max_open_positions": 3,
        "max_leverage": 5,
        "max_total_exposure_pct": 25.0,
        "max_trades_per_day": 20,
        "max_consecutive_losses": 3,
        "min_risk_reward": 1.5,
        "cooldown_seconds": 300,
        "trailing_stop_enabled": True,
        "trailing_stop_pct": 1.0,
        "trailing_take_profit_enabled": True,
        "trailing_take_profit_activation_pct": 1.0,
        "trailing_take_profit_pct": 0.5,
        "break_even_enabled": True,
        "trading_direction": "BOTH",
        "entry_mode": "AUTONOMOUS_PAPER",
        "min_opportunity_score": 70,
        "min_liquidity_usd": 50000,
        "min_24h_volume_usd": 1000000,
        "scanner_interval_seconds": 60,
        "max_watchlist_symbols": 100,
        "market_regime_filter_enabled": True,
        "exchange_enabled": {"binance": False, "bybit": False, "delta": False},
        "strategy_enabled": {
            "order_book_imbalance": True,
            "absorption": True,
            "liquidity_zones": True,
            "trade_flow_momentum": True,
            "market_regime": True,
        },
    },
    "watchlist": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    "events": [],
    "updated_at": time.time(),
    "autonomous_engine_integrated": True,
}

class ConfigRequest(BaseModel):
    config: dict[str, Any]
class WatchlistRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=20)
class EngineCommandRequest(BaseModel):
    command: str

def _auth(token: str | None):
    expected = os.getenv("CONTROL_API_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="CONTROL_API_TOKEN is not configured on the backend. Control actions are disabled.")
    if not token or token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing control token.")

def _event(event: str, details: dict[str, Any] | None = None):
    row = {"timestamp": time.time(), "event": event, "details": details or {}}
    state["events"].append(row)
    state["events"] = state["events"][-200:]
    state["updated_at"] = row["timestamp"]
    return row

@router.get("/status")
def control_status():
    return {k: state[k] for k in ("engine_state", "mode", "config", "watchlist", "updated_at", "autonomous_engine_integrated")} | {"runtime": runtime.status() if runtime else {"connected": False}}

@router.get("/events")
def control_events(limit: int = 100):
    limit = max(1, min(int(limit), 200))
    return {"events": state["events"][-limit:]}

@router.post("/engine")
async def engine_command(request: EngineCommandRequest, x_control_token: str | None = Header(default=None)):
    _auth(x_control_token)
    command = request.command.upper().strip()
    if command not in {"START", "PAUSE", "RESUME", "STOP", "EMERGENCY_HALT"}:
        raise HTTPException(status_code=400, detail="Unsupported engine command.")
    if runtime is None:
        raise HTTPException(status_code=503, detail="Runtime service is not connected.")
    try:
        if command == "START":
            await runtime.start()
            state["engine_state"] = "RUNNING"
        elif command == "PAUSE":
            runtime.pause()
            state["engine_state"] = "PAUSED"
        elif command == "RESUME":
            runtime.resume()
            state["engine_state"] = "RUNNING"
        else:
            await runtime.stop()
            state["engine_state"] = "STOPPED"
        _event("engine_command_applied", {"command": command})
        return {"applied": True, "command": command, "engine_state": state["engine_state"], "runtime": runtime.status()}
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

@router.put("/config")
def update_config(request: ConfigRequest, x_control_token: str | None = Header(default=None)):
    _auth(x_control_token)
    allowed = set(state["config"])
    numeric_limits = {
        "risk_per_trade_pct": (0.01, 5), "max_daily_loss_pct": (0.1, 20),
        "max_open_positions": (1, 50), "max_leverage": (1, 5),
        "max_total_exposure_pct": (1, 100), "max_trades_per_day": (1, 500),
        "max_consecutive_losses": (1, 20), "min_risk_reward": (0.1, 20),
        "cooldown_seconds": (0, 86400), "trailing_stop_pct": (0.05, 50),
        "trailing_take_profit_activation_pct": (0.05, 50), "trailing_take_profit_pct": (0.05, 50),
        "min_opportunity_score": (0, 100), "min_liquidity_usd": (0, 10000000000),
        "min_24h_volume_usd": (0, 10000000000), "scanner_interval_seconds": (5, 600),
        "max_watchlist_symbols": (1, 200),
    }
    enum_choices = {
        "trading_direction": {"LONG", "SHORT", "BOTH"},
        "entry_mode": {"AUTONOMOUS_PAPER", "MANUAL_APPROVAL"},
    }
    for key, value in request.config.items():
        if key not in allowed:
            raise HTTPException(status_code=400, detail=f"Unknown configuration field: {key}")
        if key in enum_choices:
            if not isinstance(value, str) or value not in enum_choices[key]:
                raise HTTPException(status_code=422, detail=f"Invalid value for {key}.")
        elif key == "strategy_enabled":
            current_keys = set(state["config"]["strategy_enabled"])
            if not isinstance(value, dict) or set(value) - current_keys or any(not isinstance(v, bool) for v in value.values()):
                raise HTTPException(status_code=422, detail="strategy_enabled must contain known strategy keys with boolean values.")
        elif key.endswith("_enabled"):
            if not isinstance(value, bool):
                raise HTTPException(status_code=422, detail=f"{key} must be boolean.")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise HTTPException(status_code=422, detail=f"{key} must be numeric.")
            if key in numeric_limits and not numeric_limits[key][0] <= float(value) <= numeric_limits[key][1]:
                raise HTTPException(status_code=422, detail=f"{key} must be between {numeric_limits[key][0]} and {numeric_limits[key][1]}.")
    if "strategy_enabled" in request.config:
        state["config"]["strategy_enabled"].update(request.config["strategy_enabled"])
        remaining = {k: v for k, v in request.config.items() if k != "strategy_enabled"}
        state["config"].update(remaining)
    else:
        state["config"].update(request.config)
    if runtime is not None:
        runtime.apply_config(state["config"])
    _event("configuration_updated", request.config)
    return {"accepted": True, "config": state["config"], "persisted": False, "message": "Configuration applied to runtime process memory; no automatic trade execution is enabled."}

@router.post("/watchlist/add")
def watchlist_add(request: WatchlistRequest, x_control_token: str | None = Header(default=None)):
    _auth(x_control_token)
    symbol = request.symbol.upper().strip()
    if not symbol.replace("USDT", "").isalnum():
        raise HTTPException(status_code=422, detail="Symbol must contain letters/numbers and optional USDT suffix.")
    if symbol not in state["watchlist"]:
        if len(state["watchlist"]) >= int(state["config"]["max_watchlist_symbols"]):
            raise HTTPException(status_code=422, detail="Watchlist capacity limit reached.")
        state["watchlist"].append(symbol)
        _event("watchlist_added", {"symbol": symbol})
    return {"watchlist": state["watchlist"]}

@router.post("/watchlist/remove")
def watchlist_remove(request: WatchlistRequest, x_control_token: str | None = Header(default=None)):
    _auth(x_control_token)
    symbol = request.symbol.upper().strip()
    if symbol in state["watchlist"]:
        state["watchlist"].remove(symbol)
        _event("watchlist_removed", {"symbol": symbol})
    return {"watchlist": state["watchlist"]}
