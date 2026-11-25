"""Phase 14 operational monitoring helpers."""
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
        if len(self.events)>self.max_events: self.events=self.events[-self.max_events:]
        if level.lower()=="error": self.last_error=event
        return item

    def health(self):
        return {"status":"ok","service":"orderflow-scalper-api","uptime_seconds":round(time.time()-self.started_at,2),"environment":os.getenv("ENVIRONMENT","development"),"python_version":platform.python_version()}

    def diagnostics(self, app: Any):
        state_keys=("market_stream","unified_market_data","exchange_manager","paper_trading_engine","backtesting_engine")
        states={k:hasattr(app.state,k) for k in state_keys}
        return {"status":"ok" if all(states.values()) else "degraded","uptime_seconds":round(time.time()-self.started_at,2),"initialized_components":states,"last_error":self.last_error,"event_count":len(self.events)}

    def recent_events(self, limit:int=100):
        limit=max(1,min(int(limit),self.max_events))
        return {"events":self.events[-limit:],"count":min(limit,len(self.events))}
