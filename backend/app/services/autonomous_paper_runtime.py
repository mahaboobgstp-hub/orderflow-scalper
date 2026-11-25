"""Operator-controlled paper runtime with nine-layer evaluation; paper-only execution."""
from __future__ import annotations
import asyncio, time
from typing import Any

class AutonomousPaperRuntime:
    def __init__(self, scanner, paper_engine, config:dict[str,Any], watchlist:list[str],
                 market_data=None, imbalance=None, absorption=None, zones=None, trade_flow=None,
                 risk_engine=None, decision_engine=None, repository=None, broader_symbol="BTCUSDT"):
        self.scanner=scanner; self.paper_engine=paper_engine
        self.market_data=market_data; self.imbalance=imbalance; self.absorption=absorption
        self.zones=zones; self.trade_flow=trade_flow; self.risk_engine=risk_engine
        self.decision_engine=decision_engine
        self.config=dict(config); self.watchlist=list(watchlist); self.broader_symbol=broader_symbol
        self._task=None; self._running=False; self._paused=False
        self._last_scan=None; self._last_error=None; self._scan_count=0; self._started_at=None; self._last_scan_time=None
        self._decisions=[]; self._last_decisions_by_symbol={}; self._logged_signatures={}

    def status(self):
        return {"connected":True,"state":"RUNNING" if self._running and not self._paused else "PAUSED" if self._running else "STOPPED",
            "mode":"PAPER_ONLY","automatic_order_execution":False,"scan_count":self._scan_count,
            "last_scan_time":self._last_scan_time,"last_error":self._last_error,
            "last_scan_summary":self._last_scan,"watchlist_count":len(self.watchlist),
            "decision_engine":"nine_layer_decision_engine" if self.decision_engine else "NOT_CONFIGURED",
            "decision_count":len(self._decisions),"recent_decisions":self._decisions[-10:],
            "guardrails":["No exchange orders","Paper simulator only","Critical unavailable layers block entry","Duplicate symbol entries refused"]}

    def apply_config(self,config):
        self.config=dict(config)
        if self.decision_engine: self.decision_engine.config=dict(config)
    def set_watchlist(self,watchlist): self.watchlist=list(watchlist)
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

    def _detect(self, detector, book, trades, *args):
        if detector is None: return None
        try: return detector.analyze(book,trades,*args)
        except (ValueError,TypeError,KeyError): return None

    def _evaluate_symbol(self, market, broader_context):
        symbol=str(market.get("symbol","")).upper()
        if not symbol or not self.market_data or not self.decision_engine: return None
        exchange_order=[x for x in ("binance","bybit","delta") if self.config.get("exchange_enabled",{}).get(x,True)]
        book=None; trades=[]; exchange=None
        for ex in exchange_order:
            candidate=self.market_data.get_book(ex,symbol)
            if candidate and candidate.get("synchronized") and not candidate.get("stale") and not candidate.get("integrity_error"):
                book=candidate; exchange=ex; trades=self.market_data.get_recent_trades(ex,symbol,500); break
        market_data={"spread_pct":market.get("spread_pct"),"quote_volume_24h":market.get("quote_volume_24h"),
            "range_24h_pct":market.get("range_24h_pct"),"price_change_24h_pct":market.get("price_change_24h_pct")}
        inputs={"market":market_data,"broader_context":broader_context}
        if book:
            inputs["imbalance"]=self._detect(self.imbalance,book,trades,10)
            inputs["absorption"]=self._detect(self.absorption,book,trades,15)
            inputs["zones"]=self._detect(self.zones,book,trades,300)
            inputs["trade_flow"]=self._detect(self.trade_flow,book,trades,15)
        # Paper portfolio risk assessment: daily loss/consecutive loss are not yet
        # reconstructed into durable guard counters, so use conservative known-state checks.
        account=self.paper_engine.account()
        equity=float(account.get("equity",0)); positions=len(self.paper_engine.positions)
        cfg=self.config
        risk_blockers=[]
        max_positions=int(cfg.get("max_open_positions",3))
        if positions>=max_positions: risk_blockers.append("MAX_OPEN_POSITIONS_REACHED")
        if symbol in self.paper_engine.positions: risk_blockers.append("DUPLICATE_SYMBOL_POSITION")
        if not book: risk_blockers.append("SYNCHRONIZED_BOOK_UNAVAILABLE")
        # Daily loss and consecutive-loss guardrails are computed from simulator history.
        today=datetime.now(timezone.utc).date()
        today_losses=sum(max(0.0,-float(t.get("net_pnl",0) or 0)) for t in self.paper_engine.closed_trades
            if datetime.fromtimestamp(int(t.get("closed_at_ms",0))/1000,timezone.utc).date()==today)
        daily_loss_limit=equity*float(cfg.get("max_daily_loss_pct",2.0))/100
        if today_losses>=daily_loss_limit: risk_blockers.append("DAILY_LOSS_LIMIT_REACHED")
        recent=self.paper_engine.closed_trades[-int(cfg.get("max_consecutive_losses",3)):]
        consecutive=0
        for trade in reversed(recent):
            if float(trade.get("net_pnl",0) or 0)<0: consecutive+=1
            else: break
        if consecutive>=int(cfg.get("max_consecutive_losses",3)): risk_blockers.append("CONSECUTIVE_LOSS_LIMIT_REACHED")
        open_risk=0.0
        for pos in self.paper_engine.positions.values():
            stop=pos.get("stop_loss_price")
            if stop:
                open_risk+=abs(float(pos.get("entry_price",0))-float(stop))*float(pos.get("quantity",0))
        next_risk=equity*float(cfg.get("risk_per_trade_pct",0.5))/100
        total_risk_limit=equity*float(cfg.get("max_total_exposure_pct",25))/100
        if open_risk+next_risk>total_risk_limit: risk_blockers.append("TOTAL_OPEN_RISK_LIMIT_WOULD_BE_EXCEEDED")
        risk={"allowed":not risk_blockers,"blockers":risk_blockers,"equity":equity,"open_positions":positions,
            "exchange":exchange,"daily_realized_loss":today_losses,"daily_loss_limit":daily_loss_limit,
            "open_stop_risk":open_risk,"open_risk_limit":total_risk_limit,"consecutive_losses":consecutive}
        result=self.decision_engine.evaluate(symbol,inputs,risk)
        result["exchange"]=exchange; result["price"]=market.get("last_price")
        # Convert decision into a guarded PAPER-only simulated order. No exchange
        # API or demo/live order endpoint is called from this runtime.
        if result.get("entry_eligible") and not risk_blockers:
            side="long" if result.get("side")=="BUY" else "short"
            price=float(market.get("last_price") or 0)
            stop_pct=float(cfg.get("initial_stop_loss_pct",cfg.get("trailing_stop_pct",1.0)))
            stop_price=price*(1-stop_pct/100) if side=="long" else price*(1+stop_pct/100)
            sizing=self.risk_engine.calculate({"symbol":symbol,"account_equity":equity,"entry_price":price,
                "stop_loss_price":stop_price,"side":side,"risk_per_trade_pct":cfg.get("risk_per_trade_pct",0.5),
                "leverage":min(float(cfg.get("max_leverage",1)),5),"max_position_notional_pct":cfg.get("max_total_exposure_pct",25)})
            if sizing.get("position_quantity",0)>0:
                try:
                    self.paper_engine.submit({"symbol":symbol,"side":side,"quantity":sizing["position_quantity"],"price":price,
                        "leverage":sizing["leverage"],"stop_loss_price":stop_price,
                        "tsl_enabled":bool(cfg.get("trailing_stop_enabled",True)),
                        "tsl_distance_pct":float(cfg.get("trailing_stop_pct",1.0)),
                        "ttp_enabled":bool(cfg.get("trailing_take_profit_enabled",True)),
                        "ttp_activation_pct":float(cfg.get("trailing_take_profit_activation_pct",1.0)),
                        "ttp_trail_pct":float(cfg.get("trailing_take_profit_pct",0.5))})
                    result["paper_execution"]={"status":"SIMULATED_OPEN","sizing":sizing}
                except (ValueError,TypeError) as exc:
                    result["paper_execution"]={"status":"REJECTED","reason":str(exc)}
            else:
                result["paper_execution"]={"status":"REJECTED","reason":"Risk sizing returned zero quantity","sizing":sizing}
        else:
            result["paper_execution"]={"status":"NOT_EXECUTED","reason":"Decision or hard risk gate did not permit entry"}
        return result

    async def _loop(self):
        while self._running:
            if not self._paused:
                try:
                    scan=await self.scanner.scan(limit=min(100,int(self.config.get("max_watchlist_symbols",100))),include_rejected=False)
                    markets=scan.get("markets",[]); watch=set(self.watchlist)
                    watched=[m for m in markets if m.get("symbol") in watch]
                    min_score=float(self.config.get("min_opportunity_score",70))
                    filtered=[m for m in markets if float(m.get("suitability_score",0))>=min_score]
                    for market in markets:
                        symbol=market.get("symbol"); price=market.get("last_price")
                        if symbol and price:
                            try: self.paper_engine.mark(symbol,float(price))
                            except (ValueError,TypeError): pass
                    # Broader context is sourced from a live scanner BTC ticker when present.
                    btc=next((m for m in markets if m.get("symbol")=="BTCUSDT"),None)
                    broader={"score":max(-50,min(50,float(btc.get("price_change_24h_pct",0))*2)),
                        "confidence":35,"reasons":["BTC 24h ticker context proxy"],"source":"scanner_ticker_proxy"} if btc else None
                    decision_rows=[]
                    for market in filtered[:min(20,int(self.config.get("decision_scan_limit",20)))]:
                        result=self._evaluate_symbol(market,broader)
                        if result:
                            decision_rows.append(result); self._last_decisions_by_symbol[result["symbol"]]=result
                    self._decisions=decision_rows[-100:]
                    self._last_scan={"scanned":scan.get("total_symbols_scanned",0),"candidate_count":scan.get("candidate_count",0),
                        "shortlist_count":len(filtered),"watchlist_candidates":[{"symbol":m.get("symbol"),"score":m.get("suitability_score"),"price":m.get("last_price")} for m in watched],
                        "top_candidates":[{"symbol":m.get("symbol"),"score":m.get("suitability_score"),"price":m.get("last_price")} for m in filtered[:10]],
                        "entry_status":"Nine-layer decisions calculated; execution remains guarded during development",
                        "decision_summary":{"evaluated":len(decision_rows),"buy":sum(x["decision"]=="BUY" for x in decision_rows),"sell":sum(x["decision"]=="SELL" for x in decision_rows),"hold":sum(x["decision"]=="HOLD" for x in decision_rows),"reject":sum(x["decision"]=="REJECT" for x in decision_rows)}}
                    self._last_scan_time=time.time(); self._scan_count+=1; self._last_error=None
                except Exception as exc:
                    self._last_error=f"{type(exc).__name__}: {str(exc)[:250]}"
            await asyncio.sleep(max(5,int(self.config.get("scanner_interval_seconds",60))))
