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
        return {"phase":12,"engine":"paper_trading_simulator","mode":"PAPER_ONLY","real_orders":False,"initial_equity":self.initial_equity,"cash_balance":round(self.cash,8),"open_positions":len(self.positions),"open_orders":0,"closed_trades":len(self.closed_trades),"fee_rate":self.fee_rate,"started_at_ms":self.session_started_ms,"management_features":["fixed_stop_loss","fixed_take_profit","trailing_stop_loss","trailing_take_profit"],"warning":"In-memory simulation. State is lost on backend restart; simulated prices are supplied by API caller."}
    def _pnl(self,p,price):
        return (price-p["entry_price"])*p["quantity"]*(1 if p["side"]=="long" else -1)
    def _position_view(self,p):
        price=self.mark_prices.get(p["symbol"],p["entry_price"]); pnl=self._pnl(p,price)
        return {**p,"mark_price":price,"unrealized_pnl":round(pnl,8),"unrealized_pnl_pct":round(pnl/p["margin"]*100,6) if p["margin"] else 0}
    def account(self):
        unrealized=sum(self._pnl(p,self.mark_prices.get(p["symbol"],p["entry_price"])) for p in self.positions.values())
        locked=sum(p["margin"] for p in self.positions.values())
        realized=sum(t["net_pnl"] for t in self.closed_trades)
        equity=self.cash+locked+unrealized
        return {"mode":"PAPER_ONLY","real_orders":False,"initial_equity":self.initial_equity,"cash_balance":round(self.cash,8),"locked_margin":round(locked,8),"unrealized_pnl":round(unrealized,8),"realized_pnl":round(realized,8),"equity":round(equity,8),"open_position_count":len(self.positions),"positions":[self._position_view(p) for p in self.positions.values()]}
    def submit(self,req:dict[str,Any]):
        symbol=str(req.get("symbol","")).upper().strip(); side=str(req.get("side","")).lower(); qty=self._finite(req.get("quantity")); price=self._finite(req.get("price")); leverage=self._finite(req.get("leverage",1))
        if not symbol or len(symbol)>30: raise ValueError("Valid symbol required.")
        if side not in ("long","short"): raise ValueError("side must be long or short.")
        if qty is None or qty<=0 or price is None or price<=0: raise ValueError("Quantity and price must be positive finite numbers.")
        if leverage is None or not 1<=leverage<=5: raise ValueError("Leverage must be between 1x and 5x.")
        if symbol in self.positions: raise ValueError("Position already open for symbol; close it before opening another.")
        notional=qty*price; margin=notional/leverage; fee=notional*self.fee_rate
        if margin+fee>self.cash: raise ValueError("Insufficient paper cash for margin plus simulated fee.")
        timestamp=int(time.time()*1000)
        mg={"stop_loss_price":self._finite(req.get("stop_loss_price")),"take_profit_price":self._finite(req.get("take_profit_price")),"tsl_enabled":bool(req.get("tsl_enabled",False)),"tsl_distance_pct":self._finite(req.get("tsl_distance_pct")),"ttp_enabled":bool(req.get("ttp_enabled",False)),"ttp_activation_pct":self._finite(req.get("ttp_activation_pct")),"ttp_trail_pct":self._finite(req.get("ttp_trail_pct"))}
        self._validate_management(side,price,mg)
        order={"order_id":str(uuid.uuid4()),"symbol":symbol,"side":side,"quantity":qty,"entry_price":price,"leverage":leverage,"notional":notional,"margin":margin,"entry_fee":fee,"status":"FILLED_SIMULATED","created_at_ms":timestamp,"mode":"PAPER_ONLY"}
        position={"position_id":str(uuid.uuid4()),"symbol":symbol,"side":side,"quantity":qty,"entry_price":price,"leverage":leverage,"notional":notional,"margin":margin,"entry_fee":fee,"opened_at_ms":timestamp,"mode":"PAPER_ONLY","best_price":price,"ttp_activated":False,"tsl_price":None,"ttp_price":None,**mg}
        self.cash-=margin+fee; self.positions[symbol]=position; self.mark_prices[symbol]=price; self.orders.append(order)
        return {"order":order,"position":self._position_view(position)}
    def mark(self,symbol:str,price:float):
        symbol=symbol.upper(); p=self._finite(price)
        if p is None or p<=0: raise ValueError("Mark price must be positive and finite.")
        self.mark_prices[symbol]=p
        if symbol not in self.positions: return {"symbol":symbol,"mark_price":p,"position_open":False}
        pos=self.positions[symbol]; side=pos["side"]
        if (side=="long" and p>pos["best_price"]) or (side=="short" and p<pos["best_price"]): pos["best_price"]=p
        if pos["tsl_enabled"]:
            d=pos["tsl_distance_pct"]/100
            pos["tsl_price"]=pos["best_price"]*(1-d) if side=="long" else pos["best_price"]*(1+d)
        if pos["ttp_enabled"]:
            gain=((pos["best_price"]-pos["entry_price"])/pos["entry_price"]*100 if side=="long" else (pos["entry_price"]-pos["best_price"])/pos["entry_price"]*100)
            if gain>=pos["ttp_activation_pct"]: pos["ttp_activated"]=True
            if pos["ttp_activated"]:
                d=pos["ttp_trail_pct"]/100
                pos["ttp_price"]=pos["best_price"]*(1-d) if side=="long" else pos["best_price"]*(1+d)
        reason=self._exit_reason(pos,p)
        if reason: return {"symbol":symbol,"mark_price":p,"position_open":False,"auto_closed":True,"closed_trade":self._close_position(symbol,p,reason)}
        return {"symbol":symbol,"mark_price":p,"position_open":True,"auto_closed":False,"position":self._position_view(pos)}
    def close(self,symbol:str,price:float):
        symbol=symbol.upper(); pos=self.positions.get(symbol); close_price=self._finite(price)
        if pos is None: raise ValueError("No open paper position for symbol.")
        if close_price is None or close_price<=0: raise ValueError("Close price must be positive and finite.")
        return self._close_position(symbol,close_price,"MANUAL_SIMULATED")
    def _validate_management(self,side,entry,m):
        sl=m["stop_loss_price"]; tp=m["take_profit_price"]
        if sl is not None and ((side=="long" and sl>=entry) or (side=="short" and sl<=entry)): raise ValueError("Stop loss must be below entry for long or above entry for short.")
        if tp is not None and ((side=="long" and tp<=entry) or (side=="short" and tp>=entry)): raise ValueError("Take profit must be above entry for long or below entry for short.")
        for k in ("tsl_distance_pct","ttp_activation_pct","ttp_trail_pct"):
            v=m[k]
            if v is not None and (v<=0 or v>=100): raise ValueError(k+" must be between 0 and 100.")
        if m["tsl_enabled"] and m["tsl_distance_pct"] is None: raise ValueError("TSL enabled requires tsl_distance_pct.")
        if m["ttp_enabled"] and (m["ttp_activation_pct"] is None or m["ttp_trail_pct"] is None): raise ValueError("TTP enabled requires activation and trail percentages.")
    def _exit_reason(self,pos,price):
        s=pos["side"]
        if pos["stop_loss_price"] is not None and ((s=="long" and price<=pos["stop_loss_price"]) or (s=="short" and price>=pos["stop_loss_price"])): return "STOP_LOSS"
        if pos["take_profit_price"] is not None and ((s=="long" and price>=pos["take_profit_price"]) or (s=="short" and price<=pos["take_profit_price"])): return "TAKE_PROFIT"
        if pos["tsl_enabled"] and pos["tsl_price"] is not None and ((s=="long" and price<=pos["tsl_price"]) or (s=="short" and price>=pos["tsl_price"])): return "TRAILING_STOP_LOSS"
        if pos["ttp_enabled"] and pos["ttp_activated"] and pos["ttp_price"] is not None and ((s=="long" and price<=pos["ttp_price"]) or (s=="short" and price>=pos["ttp_price"])): return "TRAILING_TAKE_PROFIT"
        return None
    def _close_position(self,symbol,price,reason):
        pos=self.positions[symbol]; gross=self._pnl(pos,price); exit_fee=pos["quantity"]*price*self.fee_rate; net=gross-pos["entry_fee"]-exit_fee
        self.cash+=pos["margin"]+gross-exit_fee
        record={"trade_id":str(uuid.uuid4()),"symbol":symbol,"side":pos["side"],"quantity":pos["quantity"],"entry_price":pos["entry_price"],"exit_price":price,"leverage":pos["leverage"],"gross_pnl":round(gross,8),"entry_fee":round(pos["entry_fee"],8),"exit_fee":round(exit_fee,8),"net_pnl":round(net,8),"opened_at_ms":pos["opened_at_ms"],"closed_at_ms":int(time.time()*1000),"close_reason":reason,"mode":"PAPER_ONLY"}
        self.closed_trades.append(record); del self.positions[symbol]; self.mark_prices[symbol]=price; return record
    def update_management(self,symbol,settings):
        symbol=symbol.upper(); pos=self.positions.get(symbol)
        if pos is None: raise ValueError("No open paper position.")
        keys=("stop_loss_price","take_profit_price","tsl_enabled","tsl_distance_pct","ttp_enabled","ttp_activation_pct","ttp_trail_pct")
        merged={k:settings.get(k,pos.get(k)) for k in keys}
        for k in ("stop_loss_price","take_profit_price","tsl_distance_pct","ttp_activation_pct","ttp_trail_pct"): merged[k]=self._finite(merged[k])
        self._validate_management(pos["side"],pos["entry_price"],merged); pos.update(merged)
        return {"symbol":symbol,"updated":True,"position":self._position_view(pos)}
    def history(self,limit=100):
        n=max(1,min(int(limit),500))
        return {"mode":"PAPER_ONLY","closed_trades":self.closed_trades[-n:],"orders":self.orders[-n:]}
    def reset(self,equity:float):
        v=self._finite(equity)
        if v is None or v<=0: raise ValueError("Reset equity must be positive finite number.")
        self.__init__(v,self.fee_rate); return self.status()
