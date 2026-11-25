"""Phase 4: Binance USD-M futures coin universe and scalping suitability scanner.
Public REST only; no trading or private endpoints.
"""
from __future__ import annotations
import asyncio
import time
from typing import Any
import httpx

class CoinMarketScanner:
    BASE_URL="https://fapi.binance.com"
    def __init__(self, min_quote_volume_usdt:float=5_000_000, max_spread_pct:float=0.12,
                 min_24h_range_pct:float=1.0, max_24h_range_pct:float=35.0,
                 shortlist_for_activity:int=30, request_timeout:float=8.0):
        self.min_quote_volume_usdt=min_quote_volume_usdt
        self.max_spread_pct=max_spread_pct
        self.min_24h_range_pct=min_24h_range_pct
        self.max_24h_range_pct=max_24h_range_pct
        self.shortlist_for_activity=max(0,min(shortlist_for_activity,50))
        self.request_timeout=request_timeout
        self.last_scan:dict[str,Any]|None=None
        self.last_scan_at:float|None=None
    async def _get(self,client,path,params=None):
        response=await client.get(self.BASE_URL+path,params=params)
        response.raise_for_status()
        return response.json()
    @staticmethod
    def _number(value,default=0.0):
        try: return float(value)
        except (ValueError,TypeError): return default
    @staticmethod
    def _clamp(x,lo=0,hi=100): return max(lo,min(hi,x))
    async def scan(self,limit:int=20,include_rejected:bool=False):
        limit=max(1,min(int(limit),100))
        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            info,tickers=await __import__("asyncio").gather(
                self._get(client,"/fapi/v1/exchangeInfo"),
                self._get(client,"/fapi/v1/ticker/24hr"))
            valid={s["symbol"] for s in info.get("symbols",[])
                   if s.get("status")=="TRADING" and s.get("contractType")=="PERPETUAL"
                   and s.get("quoteAsset")=="USDT" and s.get("symbol") not in {"USDCUSDT"}}
            markets=[]
            for t in tickers:
                symbol=t.get("symbol")
                if symbol not in valid: continue
                last=self._number(t.get("lastPrice")); bid=self._number(t.get("bidPrice")); ask=self._number(t.get("askPrice"))
                high=self._number(t.get("highPrice")); low=self._number(t.get("lowPrice"))
                qv=self._number(t.get("quoteVolume")); trades=self._number(t.get("count"))
                if min(last,bid,ask,high,low)<=0 or ask<bid: continue
                spread_pct=((ask-bid)/last)*100 if last else 100
                range_pct=((high-low)/last)*100 if last else 0
                # Score inputs are proxies, not probabilities or trading signals.
                liquidity_score=self._clamp((qv/self.min_quote_volume_usdt)*35)
                spread_score=self._clamp((self.max_spread_pct/max(spread_pct,0.0001))*15) if spread_pct>0 else 15
                volatility_score=self._clamp((range_pct/max(self.min_24h_range_pct,0.1))*10)
                activity_score=self._clamp((trades/10000)*20)
                momentum_score=self._clamp((self._number(t.get("priceChangePercent"))+10)*1.5)
                score=round(liquidity_score+spread_score+volatility_score+activity_score+momentum_score,2)
                reasons=[]; rejects=[]
                if qv<self.min_quote_volume_usdt: rejects.append("Low 24h quote volume")
                if spread_pct>self.max_spread_pct: rejects.append("Spread too wide")
                if range_pct<self.min_24h_range_pct: rejects.append("Insufficient daily movement")
                if range_pct>self.max_24h_range_pct: rejects.append("Extreme daily range")
                if not rejects: reasons.append("Passed basic volume/spread/range filters")
                markets.append({"symbol":symbol,"last_price":last,"quote_volume_24h":qv,
                    "trade_count_24h":int(trades),"spread_pct":round(spread_pct,5),
                    "range_24h_pct":round(range_pct,3),"price_change_24h_pct":round(self._number(t.get("priceChangePercent")),3),
                    "suitability_score":score,"status":"REJECT" if rejects else "CANDIDATE",
                    "reasons":reasons,"rejection_reasons":rejects})
            markets.sort(key=lambda x:x["suitability_score"],reverse=True)
            # Activity acceleration is measured with two adjacent 5m klines for a
            # bounded shortlist only, reducing request load and avoiding full-universe polling.
            shortlist=[m for m in markets if m["status"]=="CANDIDATE"][:self.shortlist_for_activity]
            activity={}
            async def kline(symbol):
                try:
                    rows=await self._get(client,"/fapi/v1/klines",{"symbol":symbol,"interval":"5m","limit":3})
                    if len(rows)>=3:
                        prev=self._number(rows[-3][5]); recent=self._number(rows[-2][5])
                        if prev>0: return symbol,round(recent/prev,3)
                except Exception:
                    return symbol,None
                return symbol,None
            results=await asyncio.gather(*(kline(m["symbol"]) for m in shortlist))
            activity=dict(results)
            for m in markets:
                ratio=activity.get(m["symbol"])
                m["volume_acceleration_ratio_5m"]=ratio
                if ratio is not None:
                    m["activity_acceleration_score"]=self._clamp(ratio*10,0,20)
                    m["suitability_score"]=round(m["suitability_score"]+m["activity_acceleration_score"],2)
                    m["activity_acceleration_label"]="Accelerating" if ratio>=1.25 else "Cooling" if ratio<=0.8 else "Stable"
                else:
                    m["activity_acceleration_score"]=None
                    m["activity_acceleration_label"]="Unavailable"
            markets.sort(key=lambda x:x["suitability_score"],reverse=True)
            candidates=[m for m in markets if m["status"]=="CANDIDATE"]
            selected=candidates[:limit]
            if include_rejected: selected+= [m for m in markets if m["status"]=="REJECT"][:limit]
            result={"scanner":"phase4_coin_market_selection","exchange":"binance_usdm",
                "scanned_at_ms":int(time.time()*1000),"total_symbols_scanned":len(markets),
                "candidate_count":len(candidates),"selected_count":len(selected),
                "criteria":{"min_quote_volume_usdt":self.min_quote_volume_usdt,"max_spread_pct":self.max_spread_pct,
                "min_24h_range_pct":self.min_24h_range_pct,"max_24h_range_pct":self.max_24h_range_pct,
                "activity_acceleration":"5m quote volume comparison on bounded candidate shortlist; ratio >1 indicates increase"},
                "score_note":"Suitability score is a ranking heuristic, not a probability, prediction, or trade signal.",
                "markets":selected}
            self.last_scan=result; self.last_scan_at=time.time()
            return result
