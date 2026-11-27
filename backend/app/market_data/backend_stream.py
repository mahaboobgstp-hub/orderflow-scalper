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
import time
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
        stale_after_seconds: float = 3.0,
    ):
        self.symbol = symbol.upper()
        self.stream_symbol = symbol.lower()
        self.snapshot_limit = snapshot_limit
        self.stale_after_seconds = max(0.1, float(stale_after_seconds))

        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

        self.last_update_id: int | None = None
        self.connected = False
        self.synchronized = False
        self.last_error: str | None = None
        self.connected_at: float | None = None
        self.last_event_at: float | None = None
        # Timestamp only when a depth update advances the book sequence.
        self.last_book_update_at: float | None = None
        self.last_sync_at: float | None = None
        self.last_disconnect_at: float | None = None
        self.messages_received = 0
        self.snapshot_count = 0
        self.sequence_gap_count = 0
        self.connection_attempt_count = 0
        self.successful_connection_count = 0
        self.reconnect_count = 0
        self.recovery_count = 0
        self.last_reconnect_at: float | None = None
        self.last_recovery_at: float | None = None
        self.synchronized_since: float | None = None
        self.last_disconnect_reason: str | None = None

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

        self._record_disconnect("stop_requested")

    def _record_connection_attempt(self):
        self.connection_attempt_count += 1

    def _record_connection_success(self, now: float | None = None):
        now = time.time() if now is None else now
        self.connected = True
        self.connected_at = now
        self.successful_connection_count += 1
        if self.successful_connection_count > 1:
            self.reconnect_count += 1
            self.last_reconnect_at = now
        self.synchronized = False
        self.synchronized_since = None
        self.last_event_at = None
        self.last_book_update_at = None
        self.last_error = None

    def _record_disconnect(self, reason: str):
        now = time.time()
        self.connected = False
        self.synchronized = False
        self.synchronized_since = None
        self.last_disconnect_at = now
        self.last_disconnect_reason = reason

    def _record_synchronized(self, now: float | None = None):
        now = time.time() if now is None else now
        self.synchronized = True
        self.last_sync_at = now
        self.synchronized_since = now
        if self.successful_connection_count > 1:
            self.recovery_count += 1
            self.last_recovery_at = now

    def _apply_snapshot_bridge(self, event: dict[str, Any]) -> bool:
        """Apply the first event bridging the REST snapshot before marking the book synced."""
        if not self._event_bridges_snapshot(event):
            return False
        # The first buffered event is validated by U/u snapshot overlap, not pu.
        if not self._apply_event(event, validate_previous_sequence=False):
            return False
        self._record_synchronized()
        return True

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
                self._record_disconnect(self.last_error)
                logger.exception("Binance order-book connection failed")

            else:
                if not self._stop_event.is_set():
                    self._record_disconnect(self.last_error or "WebSocket session ended")

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

        self._record_connection_attempt()
        async with websockets.connect(
            stream_url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=2**20,
        ) as websocket:

            self._record_connection_success()

            logger.info(
                "Connected to Binance stream: %s",
                self.symbol,
            )

            # Buffer events while the REST snapshot loads.
            event_queue: asyncio.Queue = asyncio.Queue()

            async def collect_events():
                async for message in websocket:
                    event = json.loads(message)
                    self.messages_received += 1
                    self.last_event_at = time.time()
                    await event_queue.put(event)

            collector_task = asyncio.create_task(
                collect_events()
            )

            async def next_event():
                # Drain buffered messages before treating a closed collector as a
                # disconnect; otherwise a closed stream can strand synchronization.
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

                    if self._snapshot_bridge_gap(event):
                        self.sequence_gap_count += 1
                        self.last_error = "Depth stream gap before snapshot bridge; reconnecting for fresh snapshot"
                        logger.warning(self.last_error)
                        return

                    if self._event_bridges_snapshot(event):
                        async with self._lock:
                            if not self._apply_snapshot_bridge(event):
                                self.sequence_gap_count += 1
                                self.last_error = (
                                    "Snapshot bridge event failed continuity validation; "
                                    "reconnecting for a fresh snapshot"
                                )
                                return

                logger.info(
                    "Order book synchronized: %s update_id=%s",
                    self.symbol,
                    self.last_update_id,
                )

                # Process live updates.
                while not self._stop_event.is_set():
                    event = await next_event()

                    async with self._lock:
                        if not self._apply_event(event):
                            # A sequence gap occurred.
                            # Reconnect and obtain a fresh snapshot.
                            self.sequence_gap_count += 1
                            self.synchronized = False
                            self.synchronized_since = None
                            self.last_error = "Order-book sequence gap; reconnecting for snapshot recovery"
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

    @staticmethod
    def _valid_update_id(value: Any) -> bool:
        """Binance update IDs are non-negative integer sequence values, not coercible numbers."""
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    def _load_snapshot(self, snapshot: dict[str, Any]):
        if not isinstance(snapshot, dict):
            raise ValueError("Depth snapshot must be an object.")
        raw_update_id = snapshot.get("lastUpdateId")
        if not self._valid_update_id(raw_update_id):
            raise ValueError("Snapshot lastUpdateId must be a non-negative integer.")

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

        self.last_update_id = raw_update_id

        self.synchronized = False
        self.snapshot_count += 1
        self.last_error = None

    def _snapshot_bridge_gap(self, event: dict[str, Any]) -> bool:
        """Detect an initial diff that starts after the Futures snapshot boundary."""
        if self.last_update_id is None or not isinstance(event, dict):
            return False
        first_update_id = event.get("U")
        final_update_id = event.get("u")
        if not self._valid_update_id(first_update_id) or not self._valid_update_id(final_update_id):
            return False
        if first_update_id > final_update_id:
            return False
        # USD-M Futures requires U <= snapshot lastUpdateId <= u. A first
        # event beginning at L+1 is a gap; it is not a Spot-style bridge.
        return first_update_id > self.last_update_id and final_update_id >= self.last_update_id


    def _event_bridges_snapshot(
        self,
        event: dict[str, Any],
    ) -> bool:
        """
        Binance depth events contain U (first update ID) and u (final update ID).
        The first event must overlap the REST snapshot update ID.
        """

        if self.last_update_id is None or not isinstance(event, dict):
            return False

        first_update_id = event.get("U")
        final_update_id = event.get("u")
        if not self._valid_update_id(first_update_id) or not self._valid_update_id(final_update_id):
            return False

        # USD-M Futures: U <= lastUpdateId <= u.
        return first_update_id <= self.last_update_id <= final_update_id


    def _apply_event(
        self,
        event: dict[str, Any],
        *,
        validate_previous_sequence: bool = True,
    ) -> bool:
        """
        Apply a depth event.

        Returns False when sequence continuity or event IDs are invalid.
        """

        if self.last_update_id is None or not isinstance(event, dict):
            return False

        first_update_id = event.get("U")
        final_update_id = event.get("u")
        if not self._valid_update_id(first_update_id) or not self._valid_update_id(final_update_id):
            return False
        # Reject malformed ranges (U must not exceed u) before stale-event handling.
        if first_update_id > final_update_id:
            return False

        # Ignore old events after validating their sequence ID types.
        if final_update_id <= self.last_update_id:
            return True

        # USD-M Futures live diff events must carry pu; no U-only fallback is
        # permitted because it can accept a malformed or unsequenced event.
        if validate_previous_sequence:
            previous_final_id = event.get("pu")
            if not self._valid_update_id(previous_final_id):
                return False
            if previous_final_id != self.last_update_id:
                return False

        self._update_levels(
            self.bids,
            event.get("b", []),
        )

        self._update_levels(
            self.asks,
            event.get("a", []),
        )

        self.last_update_id = final_update_id
        # A progressing, accepted depth event—not mere message receipt—refreshes
        # the book's usable-data freshness clock.
        self.last_book_update_at = time.time()

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
        now = time.time()
        event_age = max(0.0, now - self.last_event_at) if self.last_event_at is not None else None
        sync_age = max(0.0, now - self.last_sync_at) if self.last_sync_at is not None else None
        recovery_age = max(0.0, now - self.last_recovery_at) if self.last_recovery_at is not None else None
        book_age = (
            max(0.0, now - self.last_book_update_at)
            if self.last_book_update_at is not None
            else None
        )
        stale = (
            not self.connected
            or not self.synchronized
            or book_age is None
            or book_age > self.stale_after_seconds
        )
        synchronized_duration = (
            max(0.0, now - self.synchronized_since)
            if self.synchronized and self.synchronized_since is not None
            else None
        )
        connected_duration = (
            max(0.0, now - self.connected_at)
            if self.connected and self.connected_at is not None
            else None
        )
        return {
            "symbol": self.symbol,
            "connected": self.connected,
            "synchronized": self.synchronized,
            "stale": stale,
            "fresh": not stale,
            "healthy": self.connected and self.synchronized and not stale,
            "stale_after_seconds": self.stale_after_seconds,
            "last_update_id": self.last_update_id,
            "last_error": self.last_error,
            "connected_duration_seconds": round(connected_duration, 3) if connected_duration is not None else None,
            "synchronized_duration_seconds": round(synchronized_duration, 3) if synchronized_duration is not None else None,
            "last_event_age_seconds": round(event_age, 3) if event_age is not None else None,
            "last_book_update_age_seconds": round(book_age, 3) if book_age is not None else None,
            "last_sync_age_seconds": round(sync_age, 3) if sync_age is not None else None,
            "last_disconnect_at": self.last_disconnect_at,
            "last_disconnect_reason": self.last_disconnect_reason,
            "connection_attempt_count": self.connection_attempt_count,
            "successful_connection_count": self.successful_connection_count,
            "reconnect_count": self.reconnect_count,
            "recovery_count": self.recovery_count,
            "last_reconnect_at": self.last_reconnect_at,
            "last_recovery_at": self.last_recovery_at,
            "last_recovery_age_seconds": round(recovery_age, 3) if recovery_age is not None else None,
            "messages_received": self.messages_received,
            "snapshot_count": self.snapshot_count,
            "sequence_gap_count": self.sequence_gap_count,
        }

    async def get_order_book(
        self,
        depth: int = 20,
    ) -> dict[str, Any] | None:

        async with self._lock:
            age_seconds = (
                max(0.0, time.time() - self.last_book_update_at)
                if self.last_book_update_at is not None
                else None
            )
            if (
                not self.connected
                or not self.synchronized
                or self.last_update_id is None
                or age_seconds is None
                or age_seconds > self.stale_after_seconds
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
                "age_seconds": round(age_seconds, 3),
                "stale": False,
                "bids": [
                    [price, quantity]
                    for price, quantity in sorted_bids
                ],
                "asks": [
                    [price, quantity]
                    for price, quantity in sorted_asks
                ],
            }
