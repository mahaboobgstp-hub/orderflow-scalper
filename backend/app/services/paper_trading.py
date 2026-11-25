"""Phase 11 in-memory paper trading simulator. Never connects to real execution."""
from __future__ import annotations
import time, uuid, math
from typing import Any

class PaperTradingEngine:
    def __init__(self, initial_equity:float=10000.0, fee_rate:float=0.0004):
        if not math.isfinite(initial_equity) or initial_equity<=0: raise ValueError("Initial equity must be positive.")
        self.initial_equity=float(initial_equity); self.cash=float(initial_equity); self.fee_rate=max(0.0,float(fee_rate))
        self.positions:dict[str,dict[str,Any]]={}; self.orders:list[dict[str,Any]]=[]; self.closed_trades:list[dict[str,Any]]=[]
        self.mark_prices:dict[str,float]={}; self.session_started_ms=int(time.time()*1000)
    @staticmethod
    def _finite(v):
        try: n=float(v); return n if math.isfinite(n) else None
        except (TypeError,ValueError): return None
    def status(self):
        return {"phase":11,"engine":"paper_trading_simulator","mode":"PAPER_ONLY","real_orders":False,"initial_equity":self.initial_equity,"cash_balance":round(self.cash,8),"open_positions":len(self.positions),"open_orders":len([o for o in self.orders if o["status"]=="OPEN"]),"closed_trades":len(self.closed_trades),"fee_rate":self.fee_rate,"started_at_ms":self.session_started_ms,"warning":"In-memory simulator. State is lost on server restart; prices/fills are simulated from user-provided prices."}
    def account(self):
        unrealized=sum(self._pnl(p,self.mark_prices.get(p["symbol"],p["entry_price"])) for p in self.positions.values())
        equity=self.cash+unrealized
        return {"mode":"PAPER_ONLY","real_orders":False,"initial_equity":self.initial_equity,"cash_balance":round(self.cash,8),"unrealized_pnl":round(unrealized,8),"realized_pnl":round(self.cash-self.initial_equity,8),"equity":round(equity,8),"open_position_count":len(self.positions),"positions":[self._position_view(p) for p in self.positions.values()]}
    def _pnl(self,p,price):
        direction=1 if p["side"]=="long" else -1
        return (price-p["entry_price"])*p["quantity"]*direction
    def _position_view(self,p):
        price=self.mark_prices.get(p["symbol"],p["entry_price"]); pnl=self._pnl(p,price)
        return {**p,"mark_price":price,"unrealized_pnl":round(pnl,8),"unrealized_pnl_pct":round(pnl/p["margin"]*100,6) if p["margin"] else 0}
    def submit(self,req:dict[str,Any]):
        symbol=str(req.get("symbol","")).upper().strip(); side=str(req.get("side","")).lower(); qty=self._finite(req.get("quantity")); price=self._finite(req.get("price")); leverage=self._finite(req.get("leverage",1))
        if not symbol or len(symbol)>30: raise ValueError("Valid symbol required.")
        if side not in ("long","short"): raise ValueError("side must be long or short.")
        if qty is None or qty<=0 or price is None or price<=0: raise ValueError("Quantity and price must be positive finite numbers.")
        if leverage is None or not 1<=leverage<=5: raise ValueError("Leverage must be between 1x and 5x.")
        if symbol in self.positions: raise ValueError("Position already open for symbol; close it before opening another.")
        notional=qty*price; margin=notional/leverage; fee=notional*self.fee_rate
        if margin+fee>self.cash: raise ValueError("Insufficient paper cash for margin plus simulated fee.")
        order={"order_id":str(uuid.uuid4()),"symbol":symbol,"side":side,"quantity":qty,"entry_price":price,"leverage":leverage,"notional":notional,"margin":margin,"entry_fee":fee,"status":"FILLED_SIMULATED","created_at_ms":int(time.time()*1000),"mode":"PAPER_ONLY"}
        self.cash-=margin+fee
        self.positions[symbol]={"position_id":str(uuid.uuid4()),"symbol":symbol,"side":side,"quantity":qty,"entry_price":price,"leverage":leverage,"notional":notional,"margin":margin,"entry_fee":fee,"opened_at_ms":order["created_at_ms"],"mode":"PAPER_ONLY"}
        self.mark_prices[symbol]=price; self.orders.append(order); return {"order":order,"position":self._position_view(self.positions[symbol])}
    def mark(self,symbol:str,price:float):
        symbol=symbol.upper(); p=self._finite(price)
        if p is None or p<=0: raise ValueError("Mark price must be positive and finite.")
        self.mark_prices[symbol]=p
        if symbol not in self.positions: return {"symbol":symbol,"mark_price":p,"position_open":False}
        return {"symbol":symbol,"mark_price":p,"position_open":True,"position":self._position_view(self.positions[symbol])}
    def close(self,symbol:str,price:float):
        symbol=symbol.upper(); p=self.positions.get(symbol); close_price=self._finite(price)
        if p is None: raise ValueError("No open paper position for symbol.")
        if close_price is None or close_price<=0: raise ValueError("Close price must be positive and finite.")
        gross=self._pnl(p,close_price); exit_fee=p["quantity"]*close_price*self.fee_rate
        self.cash+=p["margin"]+gross-exit_fee
        net=gross-p["entry_fee"]-exit_fee
        record={"trade_id":str(uuid.uuid4()),"symbol":symbol,"side":p["side"],"quantity":p["quantity"],"entry_price":p["entry_price"],"exit_price":close_price,"leverage":p["leverage"],"gross_pnl":round(gross,8),"entry_fee":round(p["entry_fee"],8),"exit_fee":round(exit_fee,8),"net_pnl":round(net,8),"opened_at_ms":p["opened_at_ms"],"closed_at_ms":int(time.time()*1000),"close_reason":"MANUAL_SIMULATED","mode":"PAPER_ONLY"}
        self.closed_trades.append(record); del self.positions[symbol]; self.mark_prices[symbol]=close_price; return record
    def history(self,limit=100):
        return {"mode":"PAPER_ONLY","closed_trades":self.closed_trades[-max(1,min(int(limit),500)):],"orders":self.orders[-max(1,min(int(limit),500)):]}
    def reset(self,equity:float):
        v=self._finite(equity)
        if v is None or v<=0: raise ValueError("Reset equity must be positive finite number.")
        self.__init__(v,self.fee_rate); return self.status()
