"""Phase 8 aggressive trade flow and momentum research engine."""
from __future__ import annotations
import math,time
from typing import Any

class TradeFlowMomentumDetector:
    def __init__(self,max_book_age_seconds:float=3.0,min_trades:int=8,history_size:int=30):
        try:
            age_limit=float(max_book_age_seconds)
            minimum=int(min_trades)
            history=int(history_size)
        except (TypeError,ValueError,OverflowError):
            raise ValueError("Invalid detector configuration.") from None
        if not math.isfinite(age_limit):
            raise ValueError("max_book_age_seconds must be finite.")
        self.max_book_age_seconds=max(.1,age_limit)
        self.min_trades=max(3,min(minimum,500))
        self.history_size=max(3,min(history,100))
        self._history:dict[str,list[dict[str,Any]]]={}

    @staticmethod
    def _finite(value):
        try:
            n=float(value)
            return n if math.isfinite(n) else None
        except (TypeError,ValueError): return None

    def analyze(self,book:dict[str,Any],trades:list[dict[str,Any]],lookback_seconds:float=15.0)->dict[str,Any]:
        if not isinstance(book,dict): raise ValueError("Normalized order book is required.")
        try:
            lookback=float(lookback_seconds)
        except (TypeError,ValueError,OverflowError):
            raise ValueError("Invalid lookback duration.") from None
        if not math.isfinite(lookback) or lookback<=0:
            raise ValueError("Lookback duration must be positive and finite.")
        lookback=min(lookback,120.0)
        if not isinstance(trades,(list,tuple)):
            trades=[]
        exchange=str(book.get("exchange","")).lower(); symbol=str(book.get("symbol","")).upper()
        if not exchange or not symbol: raise ValueError("Exchange and symbol required.")
        if not book.get("synchronized",False): raise ValueError("Unsynchronized book rejected.")
        if book.get("stale",True): raise ValueError("Stale book rejected.")
        age=self._finite(book.get("age_seconds"))
        if age is None or age>self.max_book_age_seconds: raise ValueError("Book too old.")
        if book.get("integrity_error"): raise ValueError("Book integrity error.")
        bids=[]; asks=[]
        for side,raw in ((bids,book.get("bids")),(asks,book.get("asks"))):
            for row in raw if isinstance(raw,list) else []:
                if not isinstance(row,(list,tuple)) or len(row)<2: continue
                p=self._finite(row[0]);q=self._finite(row[1])
                if p is not None and q is not None and p>0 and q>0: side.append((p,q))
        if not bids or not asks: raise ValueError("Book requires both valid sides.")
        best_bid=max(p for p,q in bids);best_ask=min(p for p,q in asks)
        if best_bid>=best_ask: raise ValueError("Crossed/locked book rejected.")
        mid=(best_bid+best_ask)/2
        now=int(time.time()*1000); cutoff=now-lookback*1000
        normalized=[]
        for tr in trades or []:
            if not isinstance(tr,dict):continue
            p=self._finite(tr.get("price"));q=self._finite(tr.get("quantity"))
            raw_ts=tr.get("received_timestamp_ms")
            if raw_ts is None: raw_ts=tr.get("exchange_timestamp_ms")
            ts=self._finite(raw_ts)
            side=str(tr.get("side","")).lower()
            if p is not None and q is not None and ts is not None and p>0 and q>0 and side in ("buy","sell") and cutoff<=ts<=now+5000:
                try:
                    ts_int=int(ts)
                except (ValueError,TypeError,OverflowError):
                    continue
                normalized.append({"price":p,"quantity":q,"side":side,"ts":ts_int})
        normalized.sort(key=lambda x:x["ts"])
        buys=[t for t in normalized if t["side"]=="buy"];sells=[t for t in normalized if t["side"]=="sell"]
        buy_qty=sum(t["quantity"] for t in buys);sell_qty=sum(t["quantity"] for t in sells);total=buy_qty+sell_qty
        delta=buy_qty-sell_qty
        ratio=delta/total if total else 0.0
        buy_notional=sum(t["price"]*t["quantity"] for t in buys);sell_notional=sum(t["price"]*t["quantity"] for t in sells)
        buy_vwap=buy_notional/buy_qty if buy_qty else None;sell_vwap=sell_notional/sell_qty if sell_qty else None
        # Short time slices from actual received timestamps; compare early to late activity.
        buckets=max(2,min(6,int(lookback)//3 or 2));span=max(1.0,lookback)/buckets
        volume=[0.0]*buckets;count=[0]*buckets;delta_b=[0.0]*buckets
        for t in normalized:
            idx=min(buckets-1,max(0,int((t["ts"]-cutoff)/1000/span)))
            volume[idx]+=t["quantity"];count[idx]+=1;delta_b[idx]+=t["quantity"] if t["side"]=="buy" else -t["quantity"]
        active=[i for i,n in enumerate(count) if n]
        if len(active)>=2:
            first,last=active[0],active[-1]
            vol_change=(volume[last]-volume[first])/volume[first]*100 if volume[first] else None
            delta_change=delta_b[last]-delta_b[first]
            activity="ACCELERATING" if volume[last]>volume[first]*1.25 else "DECELERATING" if volume[last]<volume[first]*.8 else "STEADY"
        else: vol_change=None;delta_change=None;activity="INSUFFICIENT_BUCKETS"
        if len(normalized)<self.min_trades: flow="INSUFFICIENT_DATA"
        elif ratio>=.2: flow="BUY_DOMINANT"
        elif ratio<=-.2: flow="SELL_DOMINANT"
        else: flow="BALANCED"
        # Directional price progress: compare trade VWAPs and mid, plus sequence start/end.
        start_price=normalized[0]["price"] if normalized else None;end_price=normalized[-1]["price"] if normalized else None
        price_move_pct=(end_price-start_price)/start_price*100 if start_price else 0.0
        buy_progress_pct=(mid-buy_vwap)/buy_vwap*100 if buy_vwap else None
        sell_progress_pct=(sell_vwap-mid)/sell_vwap*100 if sell_vwap else None
        # Flow/price disagreement can indicate divergence; avoid labeling reversal.
        divergence="NONE"
        if len(normalized)>=self.min_trades:
            if ratio>=.2 and price_move_pct<=0: divergence="BUY_FLOW_WITHOUT_UPWARD_PROGRESS"
            elif ratio<=-.2 and price_move_pct>=0: divergence="SELL_FLOW_WITHOUT_DOWNWARD_PROGRESS"
        score=round(max(-100,min(100,ratio*100)),2) if total else 0
        key=f"{exchange}:{symbol}"; hist=self._history.setdefault(key,[])
        hist.append({"timestamp_ms":now,"mid":mid,"delta":delta,"ratio":ratio,"price_move_pct":price_move_pct,"volume":total})
        self._history[key]=hist[-self.history_size:]
        prior=hist[-2] if len(hist)>1 else None
        delta_acceleration=(delta-prior["delta"]) if prior else None
        return {"engine":"phase8_trade_flow_momentum","exchange":exchange,"symbol":symbol,"timestamp_ms":now,
            "lookback_seconds":lookback,"trade_count":len(normalized),
            "flow_classification":flow,"momentum_activity":activity,"flow_strength_score":score,
            "metrics":{"buy_quantity":round(buy_qty,8),"sell_quantity":round(sell_qty,8),"total_quantity":round(total,8),
            "net_delta":round(delta,8),"delta_ratio":round(ratio,6),"buy_trade_count":len(buys),"sell_trade_count":len(sells),
            "buy_vwap":round(buy_vwap,8) if buy_vwap is not None else None,"sell_vwap":round(sell_vwap,8) if sell_vwap is not None else None,
            "price_move_pct":round(price_move_pct,6),"buy_price_progress_pct":round(buy_progress_pct,6) if buy_progress_pct is not None else None,
            "sell_price_progress_pct":round(sell_progress_pct,6) if sell_progress_pct is not None else None,
            "last_bucket_volume_change_pct":round(vol_change,4) if vol_change is not None else None,
            "last_bucket_net_delta_change":round(delta_change,8) if delta_change is not None else None,
            "delta_change_since_previous_sample":round(delta_acceleration,8) if delta_acceleration is not None else None},
            "divergence":divergence,"diagnostics":["Trade-flow score is descriptive, not probability of success.","Activity acceleration compares active time buckets; sparse data may be inconclusive.",
            "Trade-side correctness and timestamp quality depend on exchange adapter feed.","No signal or order is generated."]}
    def status(self):
        return {"phase":8,"engine":"aggressive_trade_flow_momentum","min_trades":self.min_trades,"history_size":self.history_size,
            "max_book_age_seconds":self.max_book_age_seconds,"tracked_symbols":len(self._history),"mode":"read_only_research"}
