"""Unified nine-layer decision engine for autonomous PAPER-only research.

Detector outputs remain evidence, not trade instructions. Missing/invalid layers are
reported as unavailable and are not silently treated as neutral evidence.
"""
from __future__ import annotations
import math
from typing import Any

LAYER_NAMES = (
    "order_book_imbalance", "absorption", "liquidity_breakout",
    "aggressive_order_flow", "momentum", "spread_liquidity",
    "volatility_regime", "broader_market_context", "risk_execution",
)

def _finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None

def _layer(name, score=None, direction="NEUTRAL", confidence=0.0, available=False, reasons=None, data=None):
    score = _finite(score)
    return {"layer":name,"score":round(max(-100,min(100,score)),2) if score is not None else None,
            "direction":direction if direction in ("BUY","SELL","NEUTRAL","BLOCK") else "NEUTRAL",
            "confidence":round(max(0,min(100,_finite(confidence) or 0)),2),
            "available":bool(available),"reasons":list(reasons or []),"data":data or {}}

class NineLayerDecisionEngine:
    """Produces a scored BUY/SELL/HOLD/REJECT decision without executing orders."""
    DEFAULT_WEIGHTS = {
        "order_book_imbalance": 16, "absorption": 12, "liquidity_breakout": 12,
        "aggressive_order_flow": 16, "momentum": 12, "spread_liquidity": 10,
        "volatility_regime": 8, "broader_market_context": 6, "risk_execution": 8,
    }
    def __init__(self, config:dict[str,Any]|None=None):
        self.config=dict(config or {})
        weights=dict(self.DEFAULT_WEIGHTS)
        supplied=self.config.get("layer_weights")
        if isinstance(supplied,dict):
            for k,v in supplied.items():
                if k in weights and _finite(v) is not None and 0<=float(v)<=100: weights[k]=float(v)
        self.weights=weights

    @staticmethod
    def _direction(score, threshold=15):
        return "BUY" if score>=threshold else "SELL" if score<=-threshold else "NEUTRAL"

    def evaluate(self, symbol:str, inputs:dict[str,Any], risk:dict[str,Any]|None=None):
        inputs=inputs if isinstance(inputs,dict) else {}
        layers={}
        def put(name, score, confidence, reasons, data=None, available=True, direction=None):
            layers[name]=_layer(name,score,direction or self._direction(score or 0),confidence,available,reasons,data)
        # L1: imbalance output is normalized from the detector's weighted imbalance.
        im=inputs.get("imbalance")
        im_metrics=(im or {}).get("metrics",{}) if isinstance(im,dict) else {}
        s=_finite(im_metrics.get("weighted_imbalance"))
        put("order_book_imbalance",s*100 if s is not None else None,(im or {}).get("quality",{}).get("score",0),
            ["Weighted bid/ask depth imbalance"],im_metrics,available=s is not None)
        # L2: aggressive volume that fails to progress may indicate absorption.
        ab=inputs.get("absorption"); am=(ab or {}).get("metrics",{}) if isinstance(ab,dict) else {}
        b=_finite(am.get("buy_absorption_score")); se=_finite(am.get("sell_absorption_score"))
        a_score=((se or 0)-(b or 0))*100 if b is not None or se is not None else None
        put("absorption",a_score,(ab or {}).get("quality",{}).get("score",0),
            ["Absorption hypothesis; interpreted as opposing-side caution"],am,available=a_score is not None)
        # L3: zone breakout/rejection classifications.
        zo=inputs.get("zones"); zones=(zo or {}).get("zones",[]) if isinstance(zo,dict) else []
        z_score=0; z_reasons=[]
        if zones:
            near=zones[0]
            state=str(near.get("interaction_state",""))
            if state=="BREAKOUT_UP": z_score=70; z_reasons.append("Price above inferred liquidity zone")
            elif state=="BREAKOUT_DOWN": z_score=-70; z_reasons.append("Price below inferred liquidity zone")
            elif state=="POSSIBLE_REJECTION": z_score=0; z_reasons.append("Possible rejection is non-directional without confirmation")
            else: z_reasons.append("No clear breakout state in nearest zone")
        put("liquidity_breakout",z_score if zones else None,60 if zones else 0,z_reasons,zones[:3],available=bool(zones))
        # L4: directional delta from the aggressive-flow detector.
        tf=inputs.get("trade_flow"); tm=(tf or {}).get("metrics",{}) if isinstance(tf,dict) else {}
        delta_ratio=_finite(tm.get("delta_ratio"))
        put("aggressive_order_flow",delta_ratio*100 if delta_ratio is not None else None,
            min(100,(tf or {}).get("trade_count",0)*8) if isinstance(tf,dict) else 0,
            ["Aggressive trade delta"],tm,available=delta_ratio is not None)
        # L5: momentum is price progress, deliberately independent of L4's trade delta.
        # Delta/flow activity may support confidence, but cannot set L5 direction.
        momentum_metrics=tm if isinstance(tm,dict) else {}
        price_move=_finite(momentum_metrics.get("price_move_pct"))
        trade_count=_finite((tf or {}).get("trade_count")) if isinstance(tf,dict) else None
        configured_min=_finite(self.config.get("momentum_min_trades",8))
        min_momentum_trades=max(3,min(500,int(configured_min))) if configured_min is not None else 8
        scale=_finite(self.config.get("momentum_price_move_scale_pct"))
        scale=scale if scale is not None and scale>0 else 0.5
        momentum_available=price_move is not None and trade_count is not None and trade_count>=min_momentum_trades
        momentum_score=max(-100,min(100,(price_move/scale)*100)) if momentum_available else None
        momentum_activity=str((tf or {}).get("momentum_activity","Momentum activity unavailable"))
        momentum_conf=0
        if momentum_available:
            momentum_conf=min(100,50+min(30,trade_count-min_momentum_trades)*2+
                (20 if momentum_activity=="ACCELERATING" else 0))
        momentum_reasons=["Price-progress momentum, not aggressive-trade delta"]
        if momentum_activity!="Momentum activity unavailable":
            momentum_reasons.append("Volume activity used for confidence support only")
        put("momentum",momentum_score,momentum_conf,momentum_reasons,
            {"price_move_pct":price_move,"score_scale_pct":scale,"trade_count":trade_count,
             "minimum_trades":min_momentum_trades,"activity":momentum_activity,
             "direction_source":"price_move_pct"},available=momentum_available)
        # L6: strict spread/liquidity gate and a bounded score.
        market=inputs.get("market",{}) if isinstance(inputs.get("market"),dict) else {}
        spread=_finite(market.get("spread_pct")); qv=_finite(market.get("quote_volume_24h"))
        configured_spread_max=_finite(self.config.get("max_spread_pct"))
        spread_max=configured_spread_max if configured_spread_max is not None and configured_spread_max>0 else 0.12
        configured_min_qv=_finite(self.config.get("min_24h_volume_usd"))
        min_qv=configured_min_qv if configured_min_qv is not None and configured_min_qv>0 else 1_000_000
        spread_valid=spread is not None and spread>=0
        volume_valid=qv is not None and qv>=0
        liquidity_ok=spread_valid and volume_valid and spread<=spread_max and qv>=min_qv
        # Fail closed: any missing/invalid input blocks Layer 6, rather than
        # letting the overall engine accidentally proceed with a neutral gate.
        l6score=60 if liquidity_ok else -100 if spread_valid and spread>spread_max else -60 if volume_valid and qv<min_qv else -80 if not spread_valid or not volume_valid else None
        l6direction="NEUTRAL" if liquidity_ok else "BLOCK"
        put("spread_liquidity",l6score,100 if liquidity_ok else 80 if l6score is not None else 0,
            ["Spread and 24-hour volume thresholds; missing/invalid inputs fail closed"],{"spread_pct":spread,"quote_volume_24h":qv,"spread_limit_pct":spread_max,"volume_minimum":min_qv,"passed":liquidity_ok,"spread_valid":spread_valid,"volume_valid":volume_valid},available=l6score is not None,direction=l6direction)
        # L7: scanner 24-hour range is only a proxy; label it explicitly.
        range_pct=_finite(market.get("range_24h_pct"))
        price_change=_finite(market.get("price_change_24h_pct"))
        regime_score=None; regime_dir="NEUTRAL"; regime_reasons=[]
        if range_pct is not None and price_change is not None:
            regime_score=max(-50,min(50,price_change*2))
            regime_dir=self._direction(regime_score,10)
            regime_reasons=["Ticker-based 24h trend/range proxy; not candle regime data"]
        put("volatility_regime",regime_score,35 if regime_score is not None else 0,regime_reasons,
            {"range_24h_pct":range_pct,"price_change_24h_pct":price_change,"proxy_only":True},available=regime_score is not None,direction=regime_dir)
        # L8: BTC context must be supplied as live market evidence. Missing is unavailable.
        context=inputs.get("broader_context")
        c_score=_finite(context.get("score")) if isinstance(context,dict) else None
        put("broader_market_context",c_score,context.get("confidence",0) if isinstance(context,dict) else 0,
            context.get("reasons",[]) if isinstance(context,dict) else ["Broader context unavailable"],context or {},available=c_score is not None)
        # L9: hard execution/risk gate, not a directional signal.
        risk=risk or {}
        blockers=list(risk.get("blockers",[]))
        risk_pass=bool(risk.get("allowed",False)) and not blockers
        put("risk_execution",100 if risk_pass else -100,100,
            ["Risk and execution gate "+("passed" if risk_pass else "blocked")],risk,available=True,direction="NEUTRAL" if risk_pass else "BLOCK")
        eligible=[layers[k] for k in LAYER_NAMES[:8] if layers[k]["available"] and layers[k]["direction"] in ("BUY","SELL")]
        total_weight=sum(self.weights[l["layer"]] for l in eligible)
        score=sum(l["score"]*self.weights[l["layer"]] for l in eligible)/total_weight if total_weight else 0
        buy_weight=sum(self.weights[l["layer"]] for l in eligible if l["direction"]=="BUY")
        sell_weight=sum(self.weights[l["layer"]] for l in eligible if l["direction"]=="SELL")
        active_count=len(eligible)
        minimum_layers=int(self.config.get("minimum_available_directional_layers",4))
        consensus=max(buy_weight,sell_weight)/total_weight if total_weight else 0
        threshold=float(self.config.get("decision_score_threshold",55))
        conflict_threshold=float(self.config.get("directional_conflict_ratio",0.65))
        decision="REJECT" if not risk_pass or layers["spread_liquidity"]["direction"]=="BLOCK" else "HOLD"
        side="BUY" if buy_weight>sell_weight else "SELL" if sell_weight>buy_weight else "NEUTRAL"
        if decision!="REJECT" and active_count>=minimum_layers and consensus>=conflict_threshold and abs(score)>=threshold:
            decision=side
        return {"engine":"nine_layer_decision_engine","version":1,"mode":"PAPER_ONLY","live_execution_enabled":False,
            "symbol":symbol.upper(),"decision":decision,"side":side if decision in ("BUY","SELL") else "NEUTRAL",
            "score":round(score,2),"consensus_ratio":round(consensus,4),"directional_layers_available":active_count,
            "minimum_layers_required":minimum_layers,"layers":layers,"weights":self.weights.copy(),
            "reasons":["Decision uses weighted layer consensus, not a raw score sum."],
            "missing_critical_layers":[k for k in ("order_book_imbalance","aggressive_order_flow","spread_liquidity","risk_execution") if not layers[k]["available"]],
            "entry_eligible":decision in ("BUY","SELL"),"paper_only":True}
