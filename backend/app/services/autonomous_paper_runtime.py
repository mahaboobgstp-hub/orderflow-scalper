"""Operator-controlled paper research runtime. It scans live public markets but does not place trades."""
from __future__ import annotations
import asyncio, time
from typing import Any

class AutonomousPaperRuntime:
    def __init__(self, scanner, paper_engine, config:dict[str,Any], watchlist:list[str]):
        self.scanner=scanner; self.paper_engine=paper_engine
        self.config=dict(config); self.watchlist=list(watchlist)
        self._task=None; self._running=False; self._paused=False
        self._last_scan=None; self._last_error=None; self._scan_count=0; self._started_at=None
        self._last_scan_time=None
    def status(self):
        return {"connected":True,"state":"RUNNING" if self._running and not self._paused else "PAUSED" if self._running else "STOPPED",
            "mode":"PAPER_ONLY","automatic_order_execution":False,"scan_count":self._scan_count,
            "last_scan_time":self._last_scan_time,"last_error":self._last_error,
            "last_scan_summary":self._last_scan,"watchlist_count":len(self.watchlist),
            "guardrails":["No exchange orders","Scanner-only; no entry signal is wired","Paper positions are marked only when a scanner result includes their symbol"]}
    def apply_config(self,config):
        self.config=dict(config)
    def set_watchlist(self,watchlist):
        self.watchlist=list(watchlist)
    async def start(self):
        if self._running:
            if self._paused: self.resume()
            return
        self._running=True; self._paused=False; self._started_at=time.time()
        self._task=asyncio.create_task(self._loop())
    def pause(self):
        if not self._running: raise RuntimeError("Engine is stopped; START it before PAUSE.")
        self._paused=True
    def resume(self):
        if not self._running: raise RuntimeError("Engine is stopped; START it before RESUME.")
        self._paused=False
    async def stop(self):
        self._running=False; self._paused=False
        task=self._task; self._task=None
        if task and task is not asyncio.current_task():
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
    async def _loop(self):
        while self._running:
            if not self._paused:
                try:
                    scan=await self.scanner.scan(limit=min(100,int(self.config.get("max_watchlist_symbols",100))),include_rejected=False)
                    markets=scan.get("markets",[])
                    watch=set(self.watchlist)
                    watched=[m for m in markets if m.get("symbol") in watch]
                    min_score=float(self.config.get("min_opportunity_score",70))
                    filtered=[m for m in markets if float(m.get("suitability_score",0))>=min_score]]
                    # Update mark prices from scanner ticker data only; never submit orders.
                    for market in markets:
                        symbol=market.get("symbol"); price=market.get("last_price")
                        if symbol and price:
                            try: self.paper_engine.mark(symbol,float(price))
                            except (ValueError,TypeError): pass
                    self._last_scan={"scanned":scan.get("total_symbols_scanned",0),"candidate_count":scan.get("candidate_count",0),
                        "shortlist_count":len(filtered),"watchlist_candidates":[{"symbol":m.get("symbol"),"score":m.get("suitability_score"),"price":m.get("last_price")} for m in watched],
                        "top_candidates":[{"symbol":m.get("symbol"),"score":m.get("suitability_score"),"price":m.get("last_price")} for m in filtered[:10]],
                        "entry_status":"DISABLED: no validated nine-layer entry signal integration"}
                    self._last_scan_time=time.time(); self._scan_count+=1; self._last_error=None
                except Exception as exc:
                    self._last_error=f"{type(exc).__name__}: {str(exc)[:250]}"
            await asyncio.sleep(max(5,int(self.config.get("scanner_interval_seconds",60))))
