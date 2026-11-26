"""Phase 9 volatility and market regime classifier. Read-only feature engine."""
from __future__ import annotations
import math
from typing import Any

class MarketRegimeContextEngine:
    @staticmethod
    def _period(value, default):
        try:
            parsed=int(value)
        except (TypeError,ValueError,OverflowError):
            parsed=default
        return parsed
    def __init__(self, history_limit: int = 500):
        self.history_limit=max(60,min(self._period(history_limit,500),1000))
    @staticmethod
    def _num(x):
        try:
            v=float(x); return v if math.isfinite(v) else None
        except (TypeError,ValueError): return None
    def analyze(self,payload:dict[str,Any],fast_period:int=12,slow_period:int=36)->dict[str,Any]:
        valid=[]
        for c in (payload.get("candles",[]) if isinstance(payload,dict) else [])[-self.history_limit:]:
            if not isinstance(c,dict): continue
            o,h,l,cl,vol=(self._num(c.get(k)) for k in ("open","high","low","close","volume"))
            if all(x is not None and x>0 for x in (o,h,l,cl)) and h>=max(o,cl) and l<=min(o,cl):
                valid.append({"open":o,"high":h,"low":l,"close":cl,"volume":max(0,vol or 0)})
        fp=max(3,min(self._period(fast_period,12),50))
        sp=max(fp+1,min(self._period(slow_period,36),200))
        if len(valid)<max(40,sp+2): raise ValueError("At least 40 valid candles are required for regime classification.")
        closes=[c["close"] for c in valid]; ranges=[(c["high"]-c["low"])/c["close"]*100 for c in valid]; returns=[(closes[i]-closes[i-1])/closes[i-1]*100 for i in range(1,len(closes))]
        def mean(xs): return sum(xs)/len(xs) if xs else 0.0
        fp=max(3,min(fp,50)); sp=max(fp+1,min(sp,200))
        fast=mean(closes[-fp:]); slow=mean(closes[-sp:]); drift=(fast-slow)/slow*100 if slow else 0
        recent=returns[-fp:]; baseline=returns[-sp:]; rvol=math.sqrt(mean([x*x for x in recent])) if recent else 0; bvol=math.sqrt(mean([x*x for x in baseline])) if baseline else 0
        rr=mean(ranges[-fp:]); br=mean(ranges[-sp:]); vr=rvol/bvol if bvol else None; range_ratio=rr/br if br else None
        trend="UPTREND" if drift>=0.12 else "DOWNTREND" if drift<=-0.12 else "RANGING"
        expansion=(vr is not None and vr>=1.5) or (range_ratio is not None and range_ratio>=1.5)
        compression=(vr is not None and vr<=0.7) and (range_ratio is not None and range_ratio<=0.8)
        vol_state="EXPANSION" if expansion else "COMPRESSION" if compression else "NORMAL"
        spike="TRUE" if range_ratio is not None and ranges[-1]>br*2.5 else "FALSE"
        if trend!="RANGING" and vol_state=="EXPANSION": regime="TRENDING_VOLATILE"
        elif trend!="RANGING" and vol_state=="COMPRESSION": regime="TRENDING_LOW_VOL"
        elif trend=="RANGING" and vol_state=="EXPANSION": regime="RANGE_VOLATILE"
        elif trend=="RANGING" and vol_state=="COMPRESSION": regime="RANGE_COMPRESSION"
        else: regime="MIXED_OR_NORMAL"
        return {"engine":"phase9_market_regime_context","symbol":payload.get("symbol"),"interval":payload.get("interval"),"data_provider":payload.get("provider","unknown"),"data_mode":payload.get("data_mode","UNKNOWN"),"is_live":bool(payload.get("is_live",False)),"candle_count":len(valid),"timestamp_ms":payload.get("generated_at_ms"),"classification":{"market_regime":regime,"trend":trend,"volatility_state":vol_state,"volatility_spike":spike},"metrics":{"fast_average_close":round(fast,8),"slow_average_close":round(slow,8),"fast_vs_slow_pct":round(drift,6),"recent_return_volatility_pct":round(rvol,6),"baseline_return_volatility_pct":round(bvol,6),"volatility_ratio":round(vr,5) if vr is not None else None,"recent_average_range_pct":round(rr,6),"baseline_average_range_pct":round(br,6),"range_ratio":round(range_ratio,5) if range_ratio is not None else None,"latest_candle_range_pct":round(ranges[-1],6)},"diagnostics":["Dummy API candles only: this is not live exchange context.","Classification thresholds are heuristic and require backtesting/calibration.","No trading signals or orders are produced."]}
