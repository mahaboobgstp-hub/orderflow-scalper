"""Phase 9 dummy market-context API adapter. Replace with real exchange OHLCV adapters later.
This module intentionally serves deterministic mock candles and is never presented as live data.
"""
from __future__ import annotations
import hashlib, math, time
from typing import Any

class DummyMarketContextAPI:
    def __init__(self, provider_name: str = "dummy_ohlcv_api"):
        self.provider_name = provider_name
    @staticmethod
    def _seed(symbol: str, interval: str) -> int:
        digest = hashlib.sha256(f"{symbol.upper()}:{interval}".encode()).hexdigest()[:8]
        return int(digest, 16)
    def get_candles(self, symbol: str, interval: str = "1m", limit: int = 120) -> dict[str, Any]:
        limit=max(40,min(int(limit),500)); seed=self._seed(symbol,interval)
        base=100.0+(seed%10000)/100.0; drift=((seed%17)-8)*0.00004; wave=((seed%23)-11)*0.00035
        candles=[]; now_ms=int(time.time()*1000); step_ms={"1m":60000,"3m":180000,"5m":300000,"15m":900000,"1h":3600000}.get(interval,60000); price=base
        for i in range(limit):
            move=drift+math.sin(i*0.21+seed%19)*wave; price*=1+move
            o=price; c=price*(1+math.sin(i*0.37+seed%11)*wave); h=max(o,c)*(1+abs(wave)*1.4); l=min(o,c)*(1-abs(wave)*1.4); v=1000+(seed%500)+abs(math.sin(i*0.61+seed%13))*800
            candles.append({"timestamp_ms":now_ms-(limit-i)*step_ms,"open":round(o,6),"high":round(h,6),"low":round(l,6),"close":round(c,6),"volume":round(v,4)}); price=c
        return {"provider":self.provider_name,"data_mode":"DUMMY","is_live":False,"symbol":symbol.upper(),"interval":interval,"candles":candles,"generated_at_ms":now_ms,"note":"Mock OHLCV for integration/testing only. Not market data."}
