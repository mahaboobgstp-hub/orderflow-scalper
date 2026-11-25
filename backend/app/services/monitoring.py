"""Operational monitoring helpers for backend readiness."""
from __future__ import annotations
import os, time, platform
from typing import Any

class MonitoringService:
    def __init__(self, app_started: float | None = None):
        self.started_at = app_started or time.time()
        self.events: list[dict[str, Any]] = []
        self.max_events = 500
        self.last_error: str | None = None

    def record(self, level: str, event: str, details: dict[str, Any] | None = None):
        item={"timestamp":time.time(),"level":level.upper(),"event":event,"details":details or {}}
        self.events.append(item)
        if len(self.events)>self.max_events:
            self.events=self.events[-self.max_events:]
        if level.lower()=="error":
            self.last_error=event
        return item

    def health(self):
        return {
            "status":"ok",
            "service":"orderflow-scalper-api",
            "uptime_seconds":round(time.time()-self.started_at,2),
            "environment":os.getenv("ENVIRONMENT","development"),
            "python_version":platform.python_version(),
            "execution_mode":"PAPER_ONLY",
            "live_execution_enabled":False,
        }

    def diagnostics(self, app: Any):
        state_keys=("market_stream","unified_market_data","exchange_manager","paper_trading_engine","backtesting_engine","coin_scanner","risk_management_engine")
        states={k:hasattr(app.state,k) for k in state_keys}
        db=getattr(app.state,"database",None)
        db_status={
            "configured":bool(getattr(db,"configured",False)),
            "connected":bool(getattr(db,"connected",False)),
            "last_error":getattr(db,"last_error",None),
        }
        exchange_manager=getattr(app.state,"exchange_manager",None)
        return {
            "status":"ok" if all(states.values()) else "degraded",
            "uptime_seconds":round(time.time()-self.started_at,2),
            "initialized_components":states,
            "database":db_status,
            "exchange_adapters_initialized":exchange_manager is not None,
            "last_error":self.last_error,
            "event_count":len(self.events),
            "execution_mode":"PAPER_ONLY",
            "live_execution_enabled":False,
        }

    def recent_events(self, limit:int=100):
        limit=max(1,min(int(limit),self.max_events))
        return {"events":self.events[-limit:],"count":min(limit,len(self.events))}
