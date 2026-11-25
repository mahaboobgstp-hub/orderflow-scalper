"""
Phase 2 exchange connectivity with Phase 3 normalized-data callback support.
Public feeds only; no order placement.
"""
import asyncio, json, logging, time
from abc import ABC, abstractmethod
from typing import Any, Callable
import websockets
logger=logging.getLogger(__name__)

class PublicExchangeAdapter(ABC):
    def __init__(self,name,enabled,url,symbol="BTCUSDT",on_message:Callable[[str,Any],None]|None=None):
        self.name=name; self.enabled=enabled; self.url=url; self.symbol=symbol.upper(); self.on_message=on_message
        self.connected=False; self.last_message_at=None; self.last_error=None; self.reconnect_count=0
        self._task=None; self._stop=asyncio.Event()
    @abstractmethod
    async def _subscribe(self,websocket): pass
    async def _on_connected(self,websocket): pass
    async def _heartbeat(self,websocket): pass
    async def start(self):
        if not self.enabled or (self._task and not self._task.done()): return
        self._stop.clear(); self._task=asyncio.create_task(self._run())
    async def stop(self):
        self._stop.set()
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
            self._task=None
        self.connected=False
    async def _run(self):
        delay=1
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url,ping_interval=20,ping_timeout=20,close_timeout=5,max_size=2**20) as ws:
                    self.connected=True; self.last_error=None; delay=1
                    logger.info("%s public websocket connected",self.name)
                    await self._on_connected(ws); await self._subscribe(ws)
                    async for msg in ws:
                        if self._stop.is_set(): break
                        self.last_message_at=time.time(); await self._heartbeat(ws)
                        if isinstance(msg,bytes): msg=msg.decode("utf-8",errors="replace")
                        try:
                            parsed=json.loads(msg)
                            if isinstance(parsed,dict) and parsed.get("success") is False:
                                self.last_error=str(parsed.get("ret_msg") or parsed.get("error") or parsed)
                            if self.on_message: self.on_message(self.name,parsed)
                        except (json.JSONDecodeError,TypeError) as err:
                            self.last_error="Message parse error: "+str(err)
            except asyncio.CancelledError: raise
            except Exception as exc:
                self.last_error=str(exc); logger.warning("%s websocket disconnected: %s",self.name,exc)
            finally: self.connected=False
            if not self._stop.is_set():
                self.reconnect_count+=1; await asyncio.sleep(delay); delay=min(delay*2,30)
    async def status(self):
        age=None if self.last_message_at is None else round(time.time()-self.last_message_at,3)
        return {"exchange":self.name,"enabled":self.enabled,"connected":self.connected,"symbol":self.symbol,
            "last_message_age_seconds":age,"reconnect_count":self.reconnect_count,"last_error":self.last_error,
            "purpose":"public feed connection and normalized data callback"}

class BinancePublicAdapter(PublicExchangeAdapter):
    def __init__(self,enabled,symbol="BTCUSDT",on_message=None):
        streams=f"{symbol.lower()}@depth@100ms/{symbol.lower()}@aggTrade"
        super().__init__("binance",enabled,f"wss://fstream.binance.com/stream?streams={streams}",symbol,on_message)
    async def _subscribe(self,websocket): return

class BybitPublicAdapter(PublicExchangeAdapter):
    def __init__(self,enabled,symbol="BTCUSDT",on_message=None):
        super().__init__("bybit",enabled,"wss://stream-testnet.bybit.com/v5/public/linear",symbol,on_message)
    async def _subscribe(self,websocket):
        await websocket.send(json.dumps({"op":"subscribe","args":[f"orderbook.50.{self.symbol}",f"publicTrade.{self.symbol}"]}))

class DeltaPublicAdapter(PublicExchangeAdapter):
    def __init__(self,enabled,symbol="BTCUSDT",on_message=None):
        super().__init__("delta",enabled,"wss://socket-ind-pub.testnet.deltaex.org",symbol,on_message)
    async def _subscribe(self,websocket):
        await websocket.send(json.dumps({"type":"subscribe","payload":{"channels":[{"name":"ob_l2","symbols":[self.symbol]},{"name":"trades","symbols":[self.symbol]}]}}))
    async def _on_connected(self,websocket):
        await websocket.send(json.dumps({"type":"enable_heartbeat"}))

class ExchangeConnectionManager:
    def __init__(self,adapters): self.adapters=adapters
    async def start(self): await asyncio.gather(*(a.start() for a in self.adapters))
    async def stop(self): await asyncio.gather(*(a.stop() for a in self.adapters),return_exceptions=True)
    async def status(self): return {"phase":3,"exchanges":[await a.status() for a in self.adapters]}
