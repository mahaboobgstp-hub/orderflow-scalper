"""Phase 7: trade-derived liquidity zones and price interaction state.

Zones are inferred from captured public trades (price clustering), not exchange
heatmaps. Descriptive classifications only; no entry/exit signals.
"""
from __future__ import annotations
import math, time
from collections import defaultdict
from typing import Any

class LiquidityZoneDetector:
    def __init__(self, max_book_age_seconds: float = 3.0, zone_band_pct: float = 0.08,
                 breakout_buffer_pct: float = 0.05, max_zones: int = 12):
        self.max_book_age_seconds=max(0.1,float(max_book_age_seconds))
        self.zone_band_pct=max(0.01,min(float(zone_band_pct),0.5))
        self.breakout_buffer_pct=max(0.01,min(float(breakout_buffer_pct),0.5))
        self.max_zones=max(2,min(int(max_zones),30))
        self._previous_state: dict[str,dict[str,str]]={}

    @staticmethod
    def _valid_levels(raw):
        out=[]
        if not isinstance(raw,list): return out
        for r in raw:
            if not isinstance(r,(list,tuple)) or len(r)<2: continue
            try: p,q=float(r[0]),float(r[1])
            except (TypeError,ValueError): continue
            if math.isfinite(p) and math.isfinite(q) and p>0 and q>0: out.append((p,q))
        return out

    def _cluster_trades(self,trades,mid,lookback_seconds):
        now=int(time.time()*1000); cutoff=now-max(1,min(float(lookback_seconds),3600))*1000
        points=[]
        for t in trades or []:
            if not isinstance(t,dict): continue
            try: p=float(t.get("price",0)); q=float(t.get("quantity",0)); ts=int(t.get("received_timestamp_ms") or t.get("exchange_timestamp_ms") or 0)
            except (ValueError,TypeError,OverflowError): continue
            if p>0 and q>0 and math.isfinite(p) and math.isfinite(q) and cutoff<=ts<=now+5000:
                points.append((p,q,ts))
        points.sort(key=lambda x:x[0])
        if not points: return []
        tolerance=mid*self.zone_band_pct/100
        clusters=[]
        for p,q,ts in points:
            if not clusters or p-clusters[-1]["high"]>tolerance:
                clusters.append({"low":p,"high":p,"volume":q,"touches":1,"last_ts":ts,"prices":[p]})
            else:
                c=clusters[-1]; c["high"]=p; c["volume"]+=q; c["touches"]+=1; c["last_ts"]=max(c["last_ts"],ts); c["prices"].append(p)
        # Retain clusters with repeat interaction and/or material volume.
        eligible=[c for c in clusters if c["touches"]>=2]
        if not eligible: eligible=clusters
        eligible.sort(key=lambda c:(c["touches"],c["volume"]),reverse=True)
        return eligible[:self.max_zones]

    def analyze(self,book:dict[str,Any],trades:list[dict[str,Any]],lookback_seconds:float=300.0)->dict[str,Any]:
        try: lookback_value=float(lookback_seconds)
        except (TypeError,ValueError): raise ValueError("Invalid lookback duration.") from None
        if not math.isfinite(lookback_value) or lookback_value<=0: raise ValueError("Lookback duration must be finite and positive.")
        lookback_value=min(lookback_value,3600.0)
        if not isinstance(book,dict): raise ValueError("Normalized order book is required.")
        exchange=str(book.get("exchange","")).lower(); symbol=str(book.get("symbol","")).upper()
        if not exchange or not symbol: raise ValueError("Exchange and symbol are required.")
        if not book.get("synchronized",False): raise ValueError("Order book is unsynchronized; zone analysis refused.")
        if book.get("stale",True): raise ValueError("Order book is stale; zone analysis refused.")
        age=book.get("age_seconds")
        try: age_value=float(age)
        except (TypeError,ValueError): raise ValueError("Invalid order-book age.") from None
        if not math.isfinite(age_value) or age_value<0 or age_value>self.max_book_age_seconds:
            raise ValueError("Order book exceeds maximum age or has invalid age.")
        if book.get("integrity_error"): raise ValueError(f"Book integrity error: {book['integrity_error']}")
        bids=self._valid_levels(book.get("bids")); asks=self._valid_levels(book.get("asks"))
        if not bids or not asks: raise ValueError("Both book sides must have valid levels.")
        bid=max(p for p,q in bids); ask=min(p for p,q in asks)
        if bid>=ask: raise ValueError("Crossed or locked book is invalid.")
        mid=(bid+ask)/2
        clusters=self._cluster_trades(trades,mid,lookback_value)
        now_ms=int(time.time()*1000); cutoff=now_ms-lookback_value*1000
        tape=[]
        for t in trades or []:
            if not isinstance(t,dict): continue
            try: p=float(t.get("price",0)); ts=int(t.get("received_timestamp_ms") or t.get("exchange_timestamp_ms") or 0)
            except (ValueError,TypeError,OverflowError): continue
            if p>0 and math.isfinite(p) and cutoff<=ts<=now_ms+5000: tape.append((ts,p))
        tape.sort()
        key=f"{exchange}:{symbol}"; prior=self._previous_state.get(key,{})
        zones=[]
        active_state={}
        for c in clusters:
            low,high=c["low"],c["high"]
            center=sum(c["prices"])/len(c["prices"])
            zone_id=f"{round(center,8)}"
            lower_break=low*(1-self.breakout_buffer_pct/100)
            upper_break=high*(1+self.breakout_buffer_pct/100)
            if mid>upper_break: position="ABOVE_ZONE"
            elif mid<lower_break: position="BELOW_ZONE"
            else: position="INSIDE_ZONE"
            proximity_pct=min(abs(mid-low),abs(mid-high))/mid*100
            approaching=position!="INSIDE_ZONE" and proximity_pct<=self.zone_band_pct
            # State transitions: current interaction state plus change from prior observation.
            prev=prior.get(zone_id)
            if position=="INSIDE_ZONE":
                state="ZONE_RETEST_OR_REENTRY" if prev in ("BREAKOUT_UP","BREAKOUT_DOWN","REJECTION_UP","REJECTION_DOWN") else "IN_ZONE"
            elif position=="ABOVE_ZONE":
                state="BREAKOUT_UP" if mid>upper_break else "ABOVE_ZONE"
            else:
                state="BREAKOUT_DOWN" if mid<lower_break else "BELOW_ZONE"
            # Heuristic only: captured tape interacted with this zone and the
            # latest captured trade is outside its buffered boundary. This is not
            # candle-close or exchange-confirmed rejection.
            tape_touched = any(low <= price <= high for _, price in tape)
            last_tape_price = tape[-1][1] if tape else None
            possible_rejection = bool(tape_touched and last_tape_price is not None and
                (last_tape_price < lower_break or last_tape_price > upper_break))
            # Do not let the tape-only rejection heuristic mask a mid-price breakout.
            if possible_rejection and state not in ("BREAKOUT_UP", "BREAKOUT_DOWN"):
                state="POSSIBLE_REJECTION"
            elif approaching: state="APPROACHING"
            zone_type="SUPPORT" if center<mid else "RESISTANCE"
            zones.append({"zone_id":zone_id,"type":zone_type,"low":round(low,8),"high":round(high,8),
                "center":round(center,8),"trade_volume_in_cluster":round(c["volume"],8),"touch_count":c["touches"],
                "last_interaction_timestamp_ms":c["last_ts"],"price_position":position,"distance_to_zone_pct":round(proximity_pct,5),
                "approaching":approaching,"possible_rejection":possible_rejection,"interaction_state":state,
                "breakout_buffer_low":round(lower_break,8),"breakout_buffer_high":round(upper_break,8)})
            active_state[zone_id]=state
        # Keep only zones present in this observation to avoid stale-state growth
        # and false re-entry when old zones disappear and later reappear.
        self._previous_state[key]=active_state
        # Displayed depth clusters: top 5 levels as separate reference zones, not historical liquidity.
        bidwalls=sorted(bids,key=lambda x:x[1],reverse=True)[:5]
        askwalls=sorted(asks,key=lambda x:x[1],reverse=True)[:5]
        depth_refs={"bid_liquidity_levels":[{"price":p,"quantity":q} for p,q in sorted(bidwalls,reverse=True)],
                    "ask_liquidity_levels":[{"price":p,"quantity":q} for p,q in sorted(askwalls)]}
        zones.sort(key=lambda z:z["distance_to_zone_pct"])
        return {"detector":"phase7_liquidity_zone_breakout","exchange":exchange,"symbol":symbol,
            "analysis_timestamp_ms":int(time.time()*1000),"lookback_seconds":lookback_value,
            "current_price_reference":{"mid":round(mid,8),"best_bid":round(bid,8),"best_ask":round(ask,8)},
            "zone_count":len(zones),"zones":zones,"current_displayed_depth_references":depth_refs,
            "interaction_legend":{"APPROACHING":"Price is near the zone, but not inside it.","IN_ZONE":"Price is trading within the inferred zone.",
            "BREAKOUT_UP":"Mid price is above the zone plus breakout buffer.","BREAKOUT_DOWN":"Mid price is below the zone minus breakout buffer.",
            "ZONE_RETEST_OR_REENTRY":"Price returned inside after a previously observed break/rejection state.",
            "POSSIBLE_REJECTION":"Captured tape touched the cluster then moved away; a heuristic, not confirmation."},
            "diagnostics":["Zones are price clusters inferred from captured trades, not exchange-provided liquidity heatmaps.",
            "Touch count is trade observations in a cluster, not verified independent tests.",
            "Breakout labels are based on current mid price relative to a configurable buffer; candle-close confirmation is not available in this engine.",
            "Possible rejection uses captured trade sequence and is heuristic; no candle-close confirmation is available.",
            "Displayed depth references are current top-level book quantities and can cancel or move.",
            "No entry, exit, reversal, or profitability signal is generated."]}
    def status(self):
        return {"phase":7,"engine":"liquidity_zone_breakout_detector","tracked_symbols":len(self._previous_state),
            "zone_band_pct":self.zone_band_pct,"breakout_buffer_pct":self.breakout_buffer_pct,
            "max_zones_per_symbol":self.max_zones,"mode":"read_only_research"}
