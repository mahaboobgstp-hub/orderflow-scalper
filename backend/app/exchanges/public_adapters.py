"""
Phase 2 exchange connectivity framework.
Connections are public-market-data only; this module does not place orders.
"""
import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import websockets

logger = logging.getLogger(__name__)


class PublicExchangeAdapter(ABC):
    def __init__(self, name: str, enabled: bool, url: str, symbol: str = "BTCUSDT"):
        self.name = name
        self.enabled = enabled
        self.url = url
        self.symbol = symbol.upper()
        self.connected = False
        self.last_message_at: float | None = None
        self.last_error: str | None = None
        self.reconnect_count = 0
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @abstractmethod
    async def _subscribe(self, websocket: Any) -> None:
        """Send venue-specific public subscription, when required."""

    async def _on_connected(self, websocket: Any) -> None:
        """One-time setup immediately after connection."""
    
    async def _heartbeat(self, websocket: Any) -> None:
        """Protocol heartbeat. WebSocket ping/pong frames are enabled by client."""

    async def start(self) -> None:
        if not self.enabled:
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.connected = False

    async def _run(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**20,
                ) as ws:
                    self.connected = True
                    self.last_error = None
                    backoff = 1
                    logger.info("%s public websocket connected", self.name)
                    await self._on_connected(ws)
                    await self._subscribe(ws)
                    async for message in ws:
                        if self._stop.is_set():
                            break
                        self.last_message_at = time.time()
                        await self._heartbeat(ws)
                        # Phase 2 intentionally records connection activity only.
                        # Payload normalization/processing belongs to Phase 3.
                        if isinstance(message, bytes):
                            message = message.decode("utf-8", errors="replace")
                        try:
                            parsed = json.loads(message)
                            if isinstance(parsed, dict) and parsed.get("success") is False:
                                self.last_error = str(parsed.get("ret_msg") or parsed.get("error") or parsed)
                        except (json.JSONDecodeError, TypeError):
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning("%s websocket disconnected: %s", self.name, exc)
            finally:
                self.connected = False
            if not self._stop.is_set():
                self.reconnect_count += 1
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def status(self) -> dict[str, Any]:
        age = None if self.last_message_at is None else round(time.time() - self.last_message_at, 3)
        return {
            "exchange": self.name,
            "enabled": self.enabled,
            "connected": self.connected,
            "symbol": self.symbol,
            "last_message_age_seconds": age,
            "reconnect_count": self.reconnect_count,
            "last_error": self.last_error,
            "purpose": "public market-data connection health only; payload processing is Phase 3",
        }


class BinancePublicAdapter(PublicExchangeAdapter):
    def __init__(self, enabled: bool, symbol: str = "BTCUSDT"):
        stream = f"{symbol.lower()}@depth@100ms"
        # Public depth stream; no API credentials required.
        super().__init__("binance", enabled, f"wss://fstream.binance.com/public/ws/{stream}", symbol)


    async def _subscribe(self, websocket: Any) -> None:
        # Binance stream is selected by URL; no JSON subscribe message required.
        return


class BybitPublicAdapter(PublicExchangeAdapter):
    def __init__(self, enabled: bool, symbol: str = "BTCUSDT"):
        super().__init__("bybit", enabled, "wss://stream-testnet.bybit.com/v5/public/linear", symbol)

    async def _subscribe(self, websocket: Any) -> None:
        await websocket.send(json.dumps({
            "op": "subscribe",
            "args": [f"orderbook.50.{self.symbol}"],
        }))


class DeltaPublicAdapter(PublicExchangeAdapter):
    def __init__(self, enabled: bool, symbol: str = "BTCUSDT"):
        super().__init__("delta", enabled, "wss://socket-ind-pub.testnet.deltaex.org", symbol)

    async def _subscribe(self, websocket: Any) -> None:
        await websocket.send(json.dumps({
            "type": "subscribe",
            "payload": {"channels": [{"name": "ob_l2", "symbols": [self.symbol]}]},
        }))

    async def _on_connected(self, websocket: Any) -> None:
        # Delta public testnet documents this heartbeat enable message.
        await websocket.send(json.dumps({"type": "enable_heartbeat"}))


class ExchangeConnectionManager:
    def __init__(self, adapters: list[PublicExchangeAdapter]):
        self.adapters = adapters

    async def start(self) -> None:
        await asyncio.gather(*(adapter.start() for adapter in self.adapters))

    async def stop(self) -> None:
        await asyncio.gather(*(adapter.stop() for adapter in self.adapters), return_exceptions=True)

    async def status(self) -> dict[str, Any]:
        return {
            "phase": 2,
            "connection_only": True,
            "exchanges": [await adapter.status() for adapter in self.adapters],
        }
