"""
Binance USDⓈ-M Futures demo order-book stream.

Market data only:
- No API key required
- No order placement
- BTCUSDT by default
"""

import asyncio
import json
import logging
from collections import deque
from typing import Any

import httpx
import websockets


logger = logging.getLogger(__name__)

REST_BASE_URL = "https://demo-fapi.binance.com"
WEBSOCKET_BASE_URL = "wss://demo-fstream.binance.com"


class BinanceOrderBookStream:
    def __init__(
        self,
        symbol: str = "BTCUSDT",
        snapshot_limit: int = 1000,
    ):
        self.symbol = symbol.upper()
        self.stream_symbol = symbol.lower()
        self.snapshot_limit = snapshot_limit

        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

        self.last_update_id: int | None = None
        self.connected = False
        self.synchronized = False
        self.last_error: str | None = None

        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._lock = asyncio.Lock()

    # --------------------------------------------------
    # Lifecycle
    # --------------------------------------------------

    async def start(self):
        """Start the background market-data connection."""

        if self._task and not self._task.done():
            return

        self._stop_event.clear()

        self._task = asyncio.create_task(
            self._run_forever()
        )

    async def stop(self):
        """Stop the background connection gracefully."""

        self._stop_event.set()

        if self._task:
            self._task.cancel()

            try:
                await self._task
            except asyncio.CancelledError:
                pass

            self._task = None

        self.connected = False
        self.synchronized = False

    # --------------------------------------------------
    # Connection and synchronization
    # --------------------------------------------------

    async def _run_forever(self):
        while not self._stop_event.is_set():
            try:
                await self._connect_and_sync()

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                self.last_error = str(exc)

                logger.exception(
                    "Binance order-book connection failed"
                )

            self.connected = False
            self.synchronized = False

            if not self._stop_event.is_set():
                await asyncio.sleep(3)

    async def _connect_and_sync(self):
        """
        Connect to the depth stream, buffer updates,
        load REST snapshot, and synchronize the book.
        """

        stream_url = (
            f"{WEBSOCKET_BASE_URL}/ws/"
            f"{self.stream_symbol}@depth@100ms"
        )

        async with websockets.connect(
            stream_url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=2**20,
        ) as websocket:

            self.connected = True
            self.synchronized = False
            self.last_error = None

            logger.info(
                "Connected to Binance stream: %s",
                self.symbol,
            )

            # Buffer events while the REST snapshot loads.
            event_queue: asyncio.Queue = asyncio.Queue()

            async def collect_events():
                async for message in websocket:
                    event = json.loads(message)
                    await event_queue.put(event)

            collector_task = asyncio.create_task(
                collect_events()
            )

            async def next_event():
                # Drain queued messages before treating a closed collector as
                # disconnect; never block forever awaiting an event that cannot arrive.
                if not event_queue.empty():
                    return event_queue.get_nowait()
                if collector_task.done():
                    if collector_task.cancelled():
                        raise ConnectionError("Binance depth stream collector was cancelled.")
                    error = collector_task.exception()
                    if error:
                        raise error
                    raise ConnectionError("Binance depth stream closed.")

                event_task = asyncio.create_task(event_queue.get())
                done, _ = await asyncio.wait(
                    {event_task, collector_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if event_task in done:
                    return event_task.result()
                if not event_queue.empty():
                    event_task.cancel()
                    try:
                        await event_task
                    except asyncio.CancelledError:
                        pass
                    return event_queue.get_nowait()
                event_task.cancel()
                try:
                    await event_task
                except asyncio.CancelledError:
                    pass
                if collector_task.cancelled():
                    raise ConnectionError("Binance depth stream collector was cancelled.")
                error = collector_task.exception()
                if error:
                    raise error
                raise ConnectionError("Binance depth stream closed.")

            try:
                snapshot = await self._fetch_snapshot()

                async with self._lock:
                    self._load_snapshot(snapshot)

                # Apply buffered events until the book is synchronized.
                while not self.synchronized:
                    event = await next_event()

                    if not isinstance(event, dict):
                        raise ConnectionError(
                            "Malformed depth event before snapshot bridge; resynchronizing."
                        )
                    first_update_id = self._parse_sequence_id(event.get("U"))
                    final_update_id = self._parse_sequence_id(event.get("u"))
                    if (
                        first_update_id is None
                        or final_update_id is None
                        or first_update_id > final_update_id
                    ):
                        raise ConnectionError(
                            "Invalid depth sequence before snapshot bridge; resynchronizing."
                        )
                    if self._snapshot_bridge_gap(event):
                        raise ConnectionError(
                            "Depth stream gap before snapshot bridge; resynchronizing."
                        )

                    if self._event_bridges_snapshot(event):
                        async with self._lock:
                            applied = self._apply_event(
                                event,
                                initial_snapshot_bridge=True,
                            )
                        if not applied:
                            raise ConnectionError(
                                "Snapshot bridge event failed validation; resynchronizing."
                            )
                        self.synchronized = True

                logger.info(
                    "Order book synchronized: %s update_id=%s",
                    self.symbol,
                    self.last_update_id,
                )

                # Process live updates.
                while not self._stop_event.is_set():
                    event = await event_queue.get()

                    async with self._lock:
                        if not self._apply_event(event):
                            # A sequence gap occurred.
                            # Reconnect and obtain a fresh snapshot.
                            logger.warning(
                                "Order-book sequence gap detected"
                            )
                            return

            finally:
                collector_task.cancel()

                try:
                    await collector_task
                except asyncio.CancelledError:
                    pass

    # --------------------------------------------------
    # REST snapshot
    # --------------------------------------------------

    async def _fetch_snapshot(self) -> dict[str, Any]:
        url = f"{REST_BASE_URL}/fapi/v1/depth"

        params = {
            "symbol": self.symbol,
            "limit": self.snapshot_limit,
        }

        async with httpx.AsyncClient(
            timeout=10
        ) as client:

            response = await client.get(
                url,
                params=params,
            )

            response.raise_for_status()

            return response.json()

    # --------------------------------------------------
    # Order-book operations
    # --------------------------------------------------

    def _load_snapshot(self, snapshot: dict[str, Any]):
        self.bids = {
            float(price): float(quantity)
            for price, quantity in snapshot.get("bids", [])
            if float(quantity) > 0
        }

        self.asks = {
            float(price): float(quantity)
            for price, quantity in snapshot.get("asks", [])
            if float(quantity) > 0
        }

        self.last_update_id = int(
            snapshot["lastUpdateId"]
        )

        self.synchronized = False

    @staticmethod
    def _parse_sequence_id(value: Any) -> int | None:
        """Parse nonnegative integer sequence IDs without bool/float truncation."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str):
            value = value.strip()
            if value and value.isascii() and value.isdigit():
                try:
                    return int(value)
                except (ValueError, OverflowError):
                    return None
        return None

    def _snapshot_bridge_gap(self, event: dict[str, Any]) -> bool:
        """Detect an initial forward gap that cannot be bridged by later events."""
        if self.last_update_id is None or not isinstance(event, dict):
            return False
        first_update_id = self._parse_sequence_id(event.get("U"))
        final_update_id = self._parse_sequence_id(event.get("u"))
        if first_update_id is None or final_update_id is None:
            return False
        if first_update_id > final_update_id:
            return False
        return first_update_id > self.last_update_id + 1

    def _event_bridges_snapshot(
        self,
        event: dict[str, Any],
    ) -> bool:
        """
        Validate Binance Futures snapshot-to-stream synchronization.
        The first accepted event must cover snapshot lastUpdateId + 1.
        Events already covered by the snapshot are discarded.
        """
        if self.last_update_id is None or not isinstance(event, dict):
            return False
        first_update_id = self._parse_sequence_id(event.get("U"))
        final_update_id = self._parse_sequence_id(event.get("u"))
        if first_update_id is None or final_update_id is None:
            return False
        if first_update_id > final_update_id:
            return False
        next_update_id = self.last_update_id + 1
        return first_update_id <= next_update_id <= final_update_id

    def _apply_event(
        self,
        event: dict[str, Any],
        initial_snapshot_bridge: bool = False,
    ) -> bool:
        """
        Apply a depth event.
        Initial bridge is validated by U/u and ignores pu, because pu refers
        to the stream predecessor rather than the REST snapshot. Subsequent
        events require pu continuity or U/u gap fallback.
        """
        if self.last_update_id is None or not isinstance(event, dict):
            return False
        first_update_id = self._parse_sequence_id(event.get("U"))
        final_update_id = self._parse_sequence_id(event.get("u"))
        if first_update_id is None or final_update_id is None:
            return False
        if first_update_id > final_update_id:
            return False

        if initial_snapshot_bridge:
            if not self._event_bridges_snapshot(event):
                return False
        else:
            if final_update_id <= self.last_update_id:
                return True
            previous_final_id = event.get("pu")
            if previous_final_id is not None:
                parsed_previous_final_id = self._parse_sequence_id(previous_final_id)
                if parsed_previous_final_id is None or parsed_previous_final_id != self.last_update_id:
                    return False
            elif first_update_id > self.last_update_id + 1:
                return False

        self._update_levels(self.bids, event.get("b", []))
        self._update_levels(self.asks, event.get("a", []))
        self.last_update_id = final_update_id
        return True

    @staticmethod
    def _update_levels(
        book: dict[float, float],
        updates: list[list[str]],
    ):
        for price_text, quantity_text in updates:
            price = float(price_text)
            quantity = float(quantity_text)

            if quantity == 0:
                book.pop(price, None)
            else:
                book[price] = quantity

    # --------------------------------------------------
    # API access methods
    # --------------------------------------------------

    async def get_status(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "connected": self.connected,
            "synchronized": self.synchronized,
            "last_update_id": self.last_update_id,
            "last_error": self.last_error,
        }

    async def get_order_book(
        self,
        depth: int = 20,
    ) -> dict[str, Any] | None:

        async with self._lock:
            if (
                not self.synchronized
                or self.last_update_id is None
            ):
                return None

            sorted_bids = sorted(
                self.bids.items(),
                key=lambda item: item[0],
                reverse=True,
            )[:depth]

            sorted_asks = sorted(
                self.asks.items(),
                key=lambda item: item[0],
            )[:depth]

            return {
                "last_update_id": self.last_update_id,
                "bids": [
                    [price, quantity]
                    for price, quantity in sorted_bids
                ],
                "asks": [
                    [price, quantity]
                    for price, quantity in sorted_asks
                ],
            }
