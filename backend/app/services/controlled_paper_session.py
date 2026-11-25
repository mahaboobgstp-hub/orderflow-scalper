"""Controlled paper-session controller for the OrderFlow Scalper development cycle.

This module provides operator-defined guardrails and session accounting for future
combined validation. It is deliberately not self-starting and performs no tests.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any
import time

@dataclass
class PaperValidationConfig:
    enabled: bool = False
    max_trades: int = 25
    max_open_positions: int = 3
    max_session_loss_pct: float = 2.0
    max_single_trade_risk_pct: float = 0.5
    max_leverage: float = 3.0
    max_session_minutes: int = 120
    require_synchronized_order_book: bool = True
    allow_short: bool = True
    allow_long: bool = True
    auto_pause_on_limit: bool = True

    def normalized(self) -> dict[str, Any]:
        data=asdict(self)
        data["max_trades"]=max(1,min(int(self.max_trades),1000))
        data["max_open_positions"]=max(1,min(int(self.max_open_positions),20))
        data["max_session_loss_pct"]=max(0.1,min(float(self.max_session_loss_pct),25.0))
        data["max_single_trade_risk_pct"]=max(0.05,min(float(self.max_single_trade_risk_pct),5.0))
        data["max_leverage"]=max(1.0,min(float(self.max_leverage),5.0))
        data["max_session_minutes"]=max(1,min(int(self.max_session_minutes),1440))
        return data

class ControlledPaperSession:
    def __init__(self, config:dict[str,Any]|None=None):
        raw=config or {}
        self.config=PaperValidationConfig(**{k:v for k,v in raw.items() if k in PaperValidationConfig.__dataclass_fields__})
        self.config_values=self.config.normalized()
        self.state="DISABLED"
        self.started_at=None
        self.started_at_ms=None
        self.start_equity=None
        self.trades_started=0
        self.closed_trades=0
        self.wins=0
        self.losses=0
        self.realized_pnl=0.0
        self.pause_reason=None
        self.events=[]

    def status(self) -> dict[str,Any]:
        elapsed=(time.time()-self.started_at) if self.started_at else 0
        return {"controller":"controlled_paper_session","mode":"PAPER_ONLY","state":self.state,
            "config":self.config_values,"started_at":self.started_at_ms,"elapsed_seconds":round(elapsed,2),
            "trades_started":self.trades_started,"closed_trades":self.closed_trades,"wins":self.wins,
            "losses":self.losses,"realized_pnl":round(self.realized_pnl,8),"pause_reason":self.pause_reason,
            "events":self.events[-30:],"live_exchange_orders":False}

    def start(self, equity:float, now:float|None=None) -> dict[str,Any]:
        if not self.config_values["enabled"]:
            raise ValueError("Controlled paper session is disabled in configuration.")
        if equity<=0:
            raise ValueError("Session starting equity must be positive.")
        now=now or time.time()
        self.started_at=now; self.started_at_ms=int(now*1000); self.start_equity=float(equity)
        self.trades_started=0; self.closed_trades=0; self.wins=0; self.losses=0; self.realized_pnl=0.0
        self.pause_reason=None; self.events=[]
        self.state="ACTIVE"
        self._record("SESSION_STARTED",{"starting_equity":equity})
        return self.status()

    def pause(self, reason:str="OPERATOR_PAUSE"):
        if self.state!="ACTIVE": raise ValueError("Session must be ACTIVE to pause.")
        self.state="PAUSED"; self.pause_reason=str(reason)[:200]; self._record("SESSION_PAUSED",{"reason":self.pause_reason})
        return self.status()

    def resume(self):
        if self.state!="PAUSED": raise ValueError("Session must be PAUSED to resume.")
        self._check_time_limit()
        if self.state=="PAUSED":
            self.state="ACTIVE"; self.pause_reason=None; self._record("SESSION_RESUMED",{})
        return self.status()

    def stop(self, reason:str="OPERATOR_STOP"):
        if self.state not in ("ACTIVE","PAUSED"): raise ValueError("Session is not running.")
        self.state="STOPPED"; self.pause_reason=str(reason)[:200]; self._record("SESSION_STOPPED",{"reason":self.pause_reason})
        return self.status()

    def entry_gate(self, side:str, synchronized_book:bool, current_equity:float|None=None) -> tuple[bool,list[str]]:
        blockers=[]
        if self.state!="ACTIVE": blockers.append("VALIDATION_SESSION_NOT_ACTIVE")
        self._check_time_limit()
        if self.state!="ACTIVE": blockers.append("SESSION_TIME_LIMIT")
        if self.trades_started>=self.config_values["max_trades"]: blockers.append("SESSION_TRADE_LIMIT_REACHED")
        if side.lower() in ("long","buy") and not self.config_values["allow_long"]: blockers.append("LONG_DISABLED_FOR_SESSION")
        if side.lower() in ("short","sell") and not self.config_values["allow_short"]: blockers.append("SHORT_DISABLED_FOR_SESSION")
        if self.config_values["require_synchronized_order_book"] and not synchronized_book: blockers.append("BOOK_SYNC_REQUIRED")
        if current_equity is not None and self.start_equity:
            loss=max(0.0,self.start_equity-current_equity)
            limit=self.start_equity*self.config_values["max_session_loss_pct"]/100
            if loss>=limit:
                blockers.append("SESSION_LOSS_LIMIT_REACHED")
                if self.config_values["auto_pause_on_limit"] and self.state=="ACTIVE":
                    self.state="PAUSED"; self.pause_reason="SESSION_LOSS_LIMIT_REACHED"; self._record("SESSION_AUTO_PAUSED",{"loss":loss,"limit":limit})
        return (not blockers),blockers

    def record_entry(self, symbol:str, side:str, metadata:dict[str,Any]|None=None):
        if self.state!="ACTIVE": return False
        self.trades_started+=1
        self._record("PAPER_ENTRY",{"symbol":symbol,"side":side,"trade_number":self.trades_started,"metadata":metadata or {}})
        if self.trades_started>=self.config_values["max_trades"]:
            if self.config_values["auto_pause_on_limit"]:
                self.state="PAUSED"; self.pause_reason="SESSION_TRADE_LIMIT_REACHED"
                self._record("SESSION_AUTO_PAUSED",{"reason":self.pause_reason})
        return True

    def record_exit(self, trade:dict[str,Any]):
        self.closed_trades+=1
        pnl=float(trade.get("net_pnl",0) or 0)
        self.realized_pnl+=pnl
        if pnl>0: self.wins+=1
        elif pnl<0: self.losses+=1
        self._record("PAPER_EXIT",{"symbol":trade.get("symbol"),"net_pnl":pnl,"exit_reason":trade.get("close_reason")})

    def _check_time_limit(self):
        if self.state=="ACTIVE" and self.started_at and (time.time()-self.started_at)>=self.config_values["max_session_minutes"]*60:
            self.state="PAUSED"; self.pause_reason="SESSION_TIME_LIMIT_REACHED"; self._record("SESSION_AUTO_PAUSED",{"reason":self.pause_reason})

    def _record(self, event:str, data:dict[str,Any]):
        self.events.append({"event":event,"at":datetime.now(timezone.utc).isoformat(),"data":data})
        self.events=self.events[-200:]
