"""Phase 6: absorption and liquidity behavior research detector.

Read-only analysis of aggressive trade flow against price progress and displayed
liquidity changes. Outputs hypotheses, not trade signals.
"""
from __future__ import annotations
import math
import time
from collections import deque
from typing import Any
from numbers import Integral, Real


class AbsorptionLiquidityDetector:
    def __init__(self, history_size: int = 30, max_book_age_seconds: float = 3.0,
                 min_trades: int = 5, absorption_threshold: float = 0.60):
        if isinstance(history_size, bool) or not isinstance(history_size, Integral):
            raise ValueError("history_size must be an integer.")
        if isinstance(min_trades, bool) or not isinstance(min_trades, Integral):
            raise ValueError("min_trades must be an integer.")
        if isinstance(max_book_age_seconds, bool) or not isinstance(max_book_age_seconds, Real):
            raise ValueError("max_book_age_seconds must be numeric.")
        if isinstance(absorption_threshold, bool) or not isinstance(absorption_threshold, Real):
            raise ValueError("absorption_threshold must be numeric.")
        self.history_size=max(3,min(int(history_size),200))
        max_age=float(max_book_age_seconds)
        threshold=float(absorption_threshold)
        if not math.isfinite(max_age) or not math.isfinite(threshold):
            raise ValueError("Detector configuration must be finite.")
        self.max_book_age_seconds=max(0.1,max_age)
        self.min_trades=max(3,min(int(min_trades),500))
        self.absorption_threshold=max(0.1,min(threshold,0.95))
        self._history: dict[str,deque[dict[str,Any]]]={}

    @staticmethod
    def _valid_levels(raw):
        out=[]
        if not isinstance(raw,list): return out
        for row in raw:
            if not isinstance(row,(list,tuple)) or len(row)<2: continue
            if isinstance(row[0], bool) or isinstance(row[1], bool): continue
            try: p,q=float(row[0]),float(row[1])
            except (ValueError,TypeError,OverflowError): continue
            if math.isfinite(p) and math.isfinite(q) and p>0 and q>0: out.append((p,q))
        return out

    @staticmethod
    def _safe_ratio(a,b):
        return a/b if b>0 else 0.0

    def analyze(self,book:dict[str,Any],trades:list[dict[str,Any]],lookback_seconds:float=15.0)->dict[str,Any]:
        if not isinstance(book,dict): raise ValueError("Normalized order book is required.")
        exchange=str(book.get("exchange","")).lower(); symbol=str(book.get("symbol","")).upper()
        if not exchange or not symbol: raise ValueError("Exchange and symbol are required.")
        if not book.get("synchronized",False): raise ValueError("Order book is unsynchronized; absorption analysis refused.")
        if book.get("stale",True): raise ValueError("Order book is stale; analysis refused.")
        age=book.get("age_seconds")
        if isinstance(age, bool) or not isinstance(age, Real):
            raise ValueError("Order book age is invalid.")
        try: age_value=float(age)
        except (TypeError,ValueError,OverflowError): raise ValueError("Order book age is invalid.")
        if not math.isfinite(age_value) or age_value<0 or age_value>self.max_book_age_seconds:
            raise ValueError("Order book exceeds maximum age or has invalid age.")
        if book.get("integrity_error"): raise ValueError(f"Book integrity error: {book['integrity_error']}")
        bids=self._valid_levels(book.get("bids")); asks=self._valid_levels(book.get("asks"))
        if not bids or not asks: raise ValueError("Both book sides must have valid levels.")
        best_bid=max(p for p,q in bids); best_ask=min(p for p,q in asks)
        if best_bid>=best_ask: raise ValueError("Crossed or locked book is invalid.")
        mid=(best_bid+best_ask)/2
        if isinstance(lookback_seconds, bool) or not isinstance(lookback_seconds, Real):
            raise ValueError("Lookback must be a finite number.")
        try: lookback=float(lookback_seconds)
        except (TypeError,ValueError,OverflowError): raise ValueError("Lookback must be a finite number.")
        if not math.isfinite(lookback): raise ValueError("Lookback must be a finite number.")
        lookback=max(1.0,min(lookback,120.0))
        now_ms=int(time.time()*1000); cutoff=now_ms-lookback*1000
        normalized=[]
        for t in trades or []:
            if not isinstance(t,dict): continue
            raw_price=t.get("price",0); raw_qty=t.get("quantity",0)
            if isinstance(raw_price, bool) or isinstance(raw_qty, bool): continue
            try: price=float(raw_price); qty=float(raw_qty)
            except (TypeError,ValueError,OverflowError): continue
            # An explicitly supplied receive timestamp is authoritative. In
            # particular, zero/invalid values must not fall through to exchange time.
            raw_ts=(t.get("received_timestamp_ms") if t.get("received_timestamp_ms") is not None
                    else t.get("exchange_timestamp_ms",0))
            if isinstance(raw_ts, bool): continue
            try:
                if isinstance(raw_ts, Integral):
                    ts=int(raw_ts)
                elif isinstance(raw_ts, Real):
                    numeric_ts=float(raw_ts)
                    if not math.isfinite(numeric_ts) or not numeric_ts.is_integer(): continue
                    ts=int(numeric_ts)
                elif isinstance(raw_ts, str) and raw_ts.strip().isdigit():
                    ts=int(raw_ts.strip())
                else:
                    continue
            except (TypeError,ValueError,OverflowError): continue
            side=str(t.get("side","")).lower()
            if side not in ("buy","sell") or price<=0 or qty<=0 or not math.isfinite(price) or not math.isfinite(qty): continue
            if ts>=cutoff and ts<=now_ms+5000: normalized.append({"price":price,"quantity":qty,"side":side,"ts":ts})
        # Sort by timestamp so temporal diagnostics are independent of arrival ordering.
        normalized.sort(key=lambda t: t["ts"])
        buy_qty=sum(t["quantity"] for t in normalized if t["side"]=="buy")
        sell_qty=sum(t["quantity"] for t in normalized if t["side"]=="sell")
        buy_count=sum(1 for t in normalized if t["side"]=="buy"); sell_count=len(normalized)-buy_count
        total_qty=buy_qty+sell_qty
        delta=buy_qty-sell_qty
        flow_ratio=self._safe_ratio(abs(delta),total_qty)
        buy_avg=self._safe_ratio(sum(t["price"]*t["quantity"] for t in normalized if t["side"]=="buy"),buy_qty)
        sell_avg=self._safe_ratio(sum(t["price"]*t["quantity"] for t in normalized if t["side"]=="sell"),sell_qty)
        # VWAP-versus-mid is a spatial comparison, not temporal price progress.
        buy_vwap_vs_mid_pct=(buy_avg-mid)/mid*100 if buy_avg and mid else 0.0
        sell_vwap_vs_mid_pct=(mid-sell_avg)/mid*100 if sell_avg and mid else 0.0
        # Current displayed liquidity at the touch, and concentration in first 5 levels.
        bid5=sorted(bids,key=lambda x:x[0],reverse=True)[:5]; ask5=sorted(asks,key=lambda x:x[0])[:5]
        bid_depth=sum(q for p,q in bid5); ask_depth=sum(q for p,q in ask5)
        key=f"{exchange}:{symbol}"; history=self._history.setdefault(key,deque(maxlen=self.history_size))
        prior=history[-1] if history else None
        history.append({"timestamp":now_ms,"mid":mid,"bid5":bid_depth,"ask5":ask_depth,"buy_qty":buy_qty,"sell_qty":sell_qty})
        replenishment=None; depletion=None
        if prior:
            # Compare quantities at the same top-5 aggregate scope across requested observations.
            replenishment={"bid_depth_change":round(bid_depth-prior["bid5"],8),"ask_depth_change":round(ask_depth-prior["ask5"],8),
                          "bid_replenished":bid_depth>prior["bid5"],"ask_replenished":ask_depth>prior["ask5"]}
            depletion={"bid_depth_change_pct":round((bid_depth-prior["bid5"])/prior["bid5"]*100,4) if prior["bid5"] else None,
                      "ask_depth_change_pct":round((ask_depth-prior["ask5"])/prior["ask5"]*100,4) if prior["ask5"] else None,
                      "bid_depleted":bid_depth<prior["bid5"],"ask_depleted":ask_depth<prior["ask5"]}
        buy_absorption_score=0.0; sell_absorption_score=0.0
        buy_progress_pct=0.0; sell_progress_pct=0.0
        prior_sample_age_ms=(now_ms-prior["timestamp"]) if prior else None
        # Temporal progress requires a recent prior midpoint sample.
        has_recent_baseline=prior is not None and 0 <= prior_sample_age_ms <= lookback*1000
        if has_recent_baseline and prior["mid"]>0:
            # Signed direction-aware temporal progress; both sides use the
            # prior midpoint as the common baseline.
            buy_progress_pct=(mid-prior["mid"])/prior["mid"]*100
            sell_progress_pct=(prior["mid"]-mid)/prior["mid"]*100
        # Without a temporal baseline, scores remain zero to avoid false absorption.
        if has_recent_baseline and len(normalized)>=self.min_trades and total_qty>0:
            buy_share=self._safe_ratio(buy_qty,total_qty); sell_share=self._safe_ratio(sell_qty,total_qty)
            buy_absorption_score=buy_share*max(0.0,1.0-min(abs(buy_progress_pct)/0.10,1.0))
            sell_absorption_score=sell_share*max(0.0,1.0-min(abs(sell_progress_pct)/0.10,1.0))
        buy_absorbed=buy_absorption_score>=self.absorption_threshold
        sell_absorbed=sell_absorption_score>=self.absorption_threshold
        if buy_absorbed and sell_absorbed: label="MIXED_ABSORPTION"
        elif buy_absorbed: label="POSSIBLE_BUY_ABSORPTION" # buy aggression may be absorbed by passive sellers
        elif sell_absorbed: label="POSSIBLE_SELL_ABSORPTION" # sell aggression may be absorbed by passive buyers
        else: label="NO_CLEAR_ABSORPTION"
        confidence_quality=min(100, round(30*(len(normalized)/self.min_trades if normalized else 0)+25*(prior is not None)+25*(book.get("synchronized") is True)+20*(book.get("stale") is False),2))
        exhaustion="INSUFFICIENT_TRADE_DATA"
        if len(normalized)>=self.min_trades:
            recent=normalized[-max(3,len(normalized)//3):]
            earlier=normalized[:max(1,len(normalized)-len(recent))]
            recent_vol=sum(t["quantity"] for t in recent); earlier_vol=sum(t["quantity"] for t in earlier)
            exhaustion="FLOW_WEAKENING" if earlier and recent_vol<earlier_vol else "FLOW_STABLE_OR_INCREASING"
        return {"detector":"phase6_absorption_liquidity_behavior","exchange":exchange,"symbol":symbol,
            "analysis_timestamp_ms":now_ms,"lookback_seconds":lookback,"trade_count":len(normalized),
            "classification":label,"metrics":{"aggressive_buy_quantity":round(buy_qty,8),"aggressive_sell_quantity":round(sell_qty,8),
            "buy_trade_count":buy_count,"sell_trade_count":sell_count,"net_aggressive_delta":round(delta,8),
            "aggressive_delta_ratio":round(delta/total_qty,6) if total_qty else 0.0,"absolute_flow_imbalance":round(flow_ratio,6),
            "buy_vwap":round(buy_avg,8) if buy_qty else None,"sell_vwap":round(sell_avg,8) if sell_qty else None,
            "mid_price":round(mid,8),"buy_price_progress_pct":round(buy_progress_pct,6),"sell_price_progress_pct":round(sell_progress_pct,6),
            "buy_vwap_vs_mid_pct":round(buy_vwap_vs_mid_pct,6),"sell_vwap_vs_mid_pct":round(sell_vwap_vs_mid_pct,6),
            "buy_absorption_score":round(buy_absorption_score,6),"sell_absorption_score":round(sell_absorption_score,6),
            "buy_absorption_candidate":buy_absorbed,"sell_absorption_candidate":sell_absorbed,
            "top5_bid_depth":round(bid_depth,8),"top5_ask_depth":round(ask_depth,8)},
            "liquidity_observation":{"previous_sample_available":prior is not None,"replenishment":replenishment,"depletion":depletion},
            "flow_exhaustion":exhaustion,"quality":{"score":confidence_quality,"note":"Evidence-quality heuristic, not a prediction or win probability."},
            "diagnostics":["Absorption is a hypothesis based on aggressive flow and sampled temporal midpoint progress.","VWAP-versus-mid metrics are spatial context, not temporal price progress.","Absorption candidates require a recent prior midpoint baseline; without it scores remain zero.","Liquidity changes are sampled on API requests; not continuous order-level tracking.","This detector is not an entry or reversal signal.","Trade-side interpretation depends on exchange feed correctness."]}
    def status(self):
        return {"phase":6,"engine":"absorption_liquidity_behavior_detector","tracked_symbols":len(self._history),
                "min_trades":self.min_trades,"absorption_threshold":self.absorption_threshold,
                "max_book_age_seconds":self.max_book_age_seconds,"history_size":self.history_size}
