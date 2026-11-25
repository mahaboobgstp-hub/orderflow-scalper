"""Phase 13 historical backtesting engine. Offline candle input only; no exchange calls."""
from __future__ import annotations
import math
from typing import Any

class BacktestEngine:
    def run(self, candles: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
        cfg = {
            "initial_equity": 10000.0, "risk_per_trade_pct": 0.5,
            "max_notional_pct": 25.0, "leverage": 3.0,
            "ema_fast": 12, "ema_slow": 36, "stop_loss_pct": 1.0,
            "take_profit_pct": 2.0, "trailing_stop_pct": 0.0,
            "fee_rate": 0.0004, "slippage_pct": 0.02,
        }
        if config: cfg.update(config)
        self._validate(candles, cfg)
        closes=[float(c["close"]) for c in candles]
        fast=self._ema(closes,int(cfg["ema_fast"])); slow=self._ema(closes,int(cfg["ema_slow"]))
        equity=float(cfg["initial_equity"]); peak=equity; max_dd=0.0
        trades=[]; position=None; equity_curve=[]
        fee=float(cfg["fee_rate"]); slip=float(cfg["slippage_pct"])/100
        stop_pct=float(cfg["stop_loss_pct"])/100; tp_pct=float(cfg["take_profit_pct"])/100
        trail_pct=float(cfg["trailing_stop_pct"])/100
        for i,c in enumerate(candles):
            price=closes[i]; timestamp=c.get("timestamp",i)
            signal=None
            if i>0 and i>=int(cfg["ema_slow"]):
                if fast[i-1]<=slow[i-1] and fast[i]>slow[i]: signal="long"
                elif fast[i-1]>=slow[i-1] and fast[i]<slow[i]: signal="short"
            # Intrabar exit checks use candle extremes and conservative stop-first precedence.
            if position:
                side=position["side"]; favorable=max(position["best_price"],float(c["high"])) if side=="long" else min(position["best_price"],float(c["low"]))
                position["best_price"]=favorable
                stop=position["stop_price"]
                if trail_pct>0:
                    trail=favorable*(1-trail_pct if side=="long" else 1+trail_pct)
                    stop=max(stop,trail) if side=="long" else min(stop,trail)
                    position["stop_price"]=stop
                exit_price=None; reason=None
                if side=="long":
                    if float(c["low"])<=stop: exit_price=stop; reason="STOP_OR_TRAILING_STOP"
                    elif tp_pct>0 and float(c["high"])>=position["take_price"]: exit_price=position["take_price"]; reason="TAKE_PROFIT"
                    elif signal=="short": exit_price=price; reason="SIGNAL_REVERSAL"
                else:
                    if float(c["high"])>=stop: exit_price=stop; reason="STOP_OR_TRAILING_STOP"
                    elif tp_pct>0 and float(c["low"])<=position["take_price"]: exit_price=position["take_price"]; reason="TAKE_PROFIT"
                    elif signal=="long": exit_price=price; reason="SIGNAL_REVERSAL"
                if exit_price is not None:
                    exit_fill=exit_price*(1-slip if side=="long" else 1+slip)
                    gross=(exit_fill-position["entry_fill"])*position["qty"]*(1 if side=="long" else -1)
                    exit_fee=abs(exit_fill*position["qty"])*fee
                    net=gross-position["entry_fee"]-exit_fee
                    equity+=net
                    trades.append({"side":side,"entry_time":position["entry_time"],"exit_time":timestamp,"entry_price":position["entry_price"],"exit_price":exit_price,"quantity":position["qty"],"gross_pnl":round(gross,8),"entry_fee":round(position["entry_fee"],8),"exit_fee":round(exit_fee,8),"net_pnl":round(net,8),"exit_reason":reason})
                    position=None
            if position is None and signal in ("long","short"):
                stop_distance=price*stop_pct
                if stop_distance>0:
                    risk_cash=max(0,equity)*float(cfg["risk_per_trade_pct"])/100
                    raw_qty=risk_cash/stop_distance
                    qty=min(raw_qty,(equity*float(cfg["max_notional_pct"])/100)/price)
                    entry_fill=price*(1+slip if signal=="long" else 1-slip)
                    notional=entry_fill*qty; entry_fee=notional*fee
                    if qty>0 and entry_fee<equity:
                        equity-=entry_fee
                        position={"side":signal,"entry_time":timestamp,"entry_price":price,"entry_fill":entry_fill,"qty":qty,"entry_fee":entry_fee,"best_price":float(c["high"]) if signal=="long" else float(c["low"]),"stop_price":price*(1-stop_pct if signal=="long" else 1+stop_pct),"take_price":price*(1+tp_pct if signal=="long" else 1-tp_pct)}
            peak=max(peak,equity); max_dd=max(max_dd,(peak-equity)/peak if peak else 0)
            equity_curve.append({"timestamp":timestamp,"equity":round(equity,8)})
        # Mark open position at last close, force-close for comparable completed runs.
        if position:
            c=candles[-1]; price=closes[-1]; side=position["side"]
            exit_fill=price*(1-slip if side=="long" else 1+slip)
            gross=(exit_fill-position["entry_fill"])*position["qty"]*(1 if side=="long" else -1)
            exit_fee=abs(exit_fill*position["qty"])*fee; net=gross-position["entry_fee"]-exit_fee; equity+=net
            trades.append({"side":side,"entry_time":position["entry_time"],"exit_time":c.get("timestamp",len(candles)-1),"entry_price":position["entry_price"],"exit_price":price,"quantity":position["qty"],"gross_pnl":round(gross,8),"entry_fee":round(position["entry_fee"],8),"exit_fee":round(exit_fee,8),"net_pnl":round(net,8),"exit_reason":"END_OF_DATA"})
            if equity_curve: equity_curve[-1]["equity"]=round(equity,8)
        return self._metrics(trades,float(cfg["initial_equity"]),equity,equity_curve,max_dd,cfg)

    @staticmethod
    def _ema(values,period):
        alpha=2/(period+1); out=[]
        current=values[0]
        for v in values:
            current=alpha*v+(1-alpha)*current; out.append(current)
        return out

    @staticmethod
    def _validate(candles,cfg):
        if not isinstance(candles,list) or len(candles)<int(cfg["ema_slow"])+2: raise ValueError("Provide candle array long enough for the slow EMA.")
        for k in ("initial_equity","risk_per_trade_pct","max_notional_pct","leverage","stop_loss_pct","fee_rate","slippage_pct"):
            if not math.isfinite(float(cfg[k])): raise ValueError(k+" must be finite.")
        if float(cfg["initial_equity"])<=0 or not 0<float(cfg["risk_per_trade_pct"])<=5: raise ValueError("Equity must be positive and risk percentage within (0,5].")
        if not 1<=float(cfg["leverage"])<=20 or not 1<=float(cfg["max_notional_pct"])<=100: raise ValueError("Leverage or notional cap out of range.")
        if not 0<float(cfg["stop_loss_pct"])<100 or not 0<=float(cfg["take_profit_pct"])<100 or not 0<=float(cfg["trailing_stop_pct"])<100: raise ValueError("SL/TP/trailing percentages out of range.")
        if not 0<=float(cfg["fee_rate"])<1 or not 0<=float(cfg["slippage_pct"])<10: raise ValueError("Fee or slippage out of range.")
        if int(cfg["ema_fast"])<2 or int(cfg["ema_slow"])<=int(cfg["ema_fast"]): raise ValueError("EMA periods must satisfy 2 <= fast < slow.")
        for c in candles:
            for key in ("open","high","low","close"):
                v=float(c[key])
                if not math.isfinite(v) or v<=0: raise ValueError("OHLC prices must be positive and finite.")
            if float(c["high"])<max(float(c["open"]),float(c["close"])) or float(c["low"])>min(float(c["open"]),float(c["close"])) or float(c["low"])>float(c["high"]): raise ValueError("Invalid candle OHLC range.")

    @staticmethod
    def _metrics(trades,initial,final,curve,max_dd,cfg):
        wins=[t["net_pnl"] for t in trades if t["net_pnl"]>0]; losses=[t["net_pnl"] for t in trades if t["net_pnl"]<0]
        gross_profit=sum(wins); gross_loss=abs(sum(losses)); total=sum(t["net_pnl"] for t in trades)
        buy=[t for t in trades if t["side"]=="long"]; sell=[t for t in trades if t["side"]=="short"]
        def side_stats(items):
            return {"trades":len(items),"net_pnl":round(sum(t["net_pnl"] for t in items),8),"win_rate_pct":round(sum(t["net_pnl"]>0 for t in items)/len(items)*100,4) if items else 0}
        return {"engine":"phase13_backtest","mode":"OFFLINE_HISTORICAL_CANDLES","strategy":"EMA_CROSS","data_is_live":False,"config":cfg,"summary":{"initial_equity":initial,"final_equity":round(final,8),"net_pnl":round(final-initial,8),"return_pct":round((final-initial)/initial*100,6),"trades":len(trades),"wins":len(wins),"losses":len(losses),"win_rate_pct":round(len(wins)/len(trades)*100,4) if trades else 0,"profit_factor":round(gross_profit/gross_loss,6) if gross_loss else (None if not gross_profit else "INF"),"average_win":round(sum(wins)/len(wins),8) if wins else 0,"average_loss":round(sum(losses)/len(losses),8) if losses else 0,"max_drawdown_pct":round(max_dd*100,6),"long":side_stats(buy),"short":side_stats(sell),"fees_included":True,"slippage_model":"fixed percentage per fill","equity_curve":curve},"trades":trades,"warnings":["This is a basic EMA-crossover baseline, not the order-book strategy.","Candle-only data cannot reproduce intrabar sequence; stop is conservatively prioritized when both stop and target touch.","No funding, liquidation, latency, partial fills, exchange lot filters, or realistic market impact.","Backtest quality depends on supplied historical data; this endpoint does not fetch exchange data."]}
