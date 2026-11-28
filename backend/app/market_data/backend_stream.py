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
import math
import time
from collections import deque
from typing import Any

import httpx
import websockets


logger = logging.getLogger(__name__)

REST_BASE_URL = "https://demo-fapi.binance.com"
WEBSOCKET_BASE_URL = "wss://demo-fstream.binance.com"

# Bound buffered depth events while REST snapshot synchronization is in progress.
SNAPSHOT_BUFFER_MAX_EVENTS = 1000
SNAPSHOT_LIMIT_OPTIONS = (5, 10, 20, 50, 100, 500, 1000)


class BinanceOrderBookStream:
    def __init__(
        self,
        symbol: str = "BTCUSDT",
        snapshot_limit: int = 1000,
        stale_after_seconds: float = 3.0,
    ):
        self.symbol = symbol.upper()
        self.stream_symbol = symbol.lower()
        if isinstance(snapshot_limit, bool) or not isinstance(snapshot_limit, int) or snapshot_limit not in SNAPSHOT_LIMIT_OPTIONS:
            raise ValueError(f"snapshot_limit must be one of {SNAPSHOT_LIMIT_OPTIONS}")
        self.snapshot_limit = snapshot_limit
        try:
            stale_cutoff = float(stale_after_seconds)
        except (TypeError, ValueError, OverflowError):
            stale_cutoff = 3.0
        if isinstance(stale_after_seconds, bool) or not math.isfinite(stale_cutoff) or stale_cutoff <= 0:
            stale_cutoff = 3.0
        self.stale_after_seconds = max(0.1, stale_cutoff)

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
        self.invalid_depth_message_count = 0
        self.snapshot_buffer_overflow_count = 0
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

    def _apply_snapshot_bridge(
        self,
        event: dict[str, Any],
        *,
        collector_task: asyncio.Task | None = None,
    ) -> bool:
        """Apply a snapshot bridge only while its WebSocket collector is active."""
        # Recheck collector state inside the lock-protected bridge application.
        # The caller's earlier check occurs before awaiting the book lock; the
        # collector may terminate while that lock is contended.
        if collector_task is not None and collector_task.done():
            self.synchronized = False
            self.synchronized_since = None
            self.last_error = self.last_error or "WebSocket ended during snapshot synchronization"
            return False
        if not self._event_bridges_snapshot(event):
            return False
        # The first buffered event is validated by U/u snapshot overlap, not pu.
        if not self._apply_event(event, validate_previous_sequence=False):
            return False
        self._record_synchronized()
        return True

    def _decode_depth_message(self, message: str | bytes) -> dict[str, Any]:
        """Decode depth frames and reject wrong event type/symbol or update-ID ranges."""
        try:
            event = json.loads(message)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise ValueError("Malformed Binance depth JSON frame") from exc
        if not isinstance(event, dict):
            raise ValueError("Binance depth frame must be a JSON object")
        if event.get("e") != "depthUpdate":
            raise ValueError("Binance depth frame has unexpected event type")
        event_symbol = event.get("s")
        if not isinstance(event_symbol, str) or event_symbol.upper() != self.symbol:
            raise ValueError("Binance depth frame symbol does not match configured symbol")
        try:
            first_raw, final_raw = event["U"], event["u"]
            if isinstance(first_raw, bool) or not isinstance(first_raw, int):
                raise ValueError("Update ID U must be a JSON integer")
            if isinstance(final_raw, bool) or not isinstance(final_raw, int):
                raise ValueError("Update ID u must be a JSON integer")
            first_update_id, final_update_id = first_raw, final_raw
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Depth frame must contain valid integer U/u update IDs") from exc
        if first_update_id < 0 or final_update_id < first_update_id:
            raise ValueError("Depth frame has an invalid U/u update-ID range")
        if "pu" not in event:
            raise ValueError("Depth frame must contain previous update ID pu")
        previous_raw = event["pu"]
        if isinstance(previous_raw, bool) or not isinstance(previous_raw, int):
            raise ValueError("Previous update ID pu must be a JSON integer")
        previous_update_id = previous_raw
        if previous_update_id < 0:
            raise ValueError("Depth frame has an invalid previous update ID pu")
        return event

    async def _collect_depth_events(self, websocket, event_queue: asyncio.Queue):
        """Collect frames into a bounded queue; overflow forces snapshot recovery."""
        overflowed = False
        try:
            async for message in websocket:
                self.messages_received += 1
                self.last_event_at = time.time()
                try:
                    event = self._decode_depth_message(message)
                except ValueError as exc:
                    self.invalid_depth_message_count += 1
                    self.last_error = str(exc)
                    logger.warning("Invalid Binance depth frame: %s", exc)
                    break
                try:
                    event_queue.put_nowait(event)
                except asyncio.QueueFull:
                    overflowed = True
                    self.snapshot_buffer_overflow_count += 1
                    self.last_error = (
                        "Depth event buffer overflow; reconnecting for fresh snapshot"
                    )
                    # Never synchronize from a partial buffer after dropping an event.
                    while True:
                        try:
                            event_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    event_queue.put_nowait(None)
                    logger.warning("Binance depth event buffer overflow; forcing snapshot recovery")
                    break
        finally:
            # A terminated collector cannot prove a live sequence. Invalidate
            # book availability before signaling the consumer, so readers fail
            # closed during the reconnect handoff.
            self.synchronized = False
            self.synchronized_since = None
            # Queue termination must never block the collector while the consumer
            # is exiting. If a full queue cannot accept the sentinel, discard
            # its partial contents and force recovery instead.
            if not overflowed:
                try:
                    event_queue.put_nowait(None)
                except asyncio.QueueFull:
                    self.snapshot_buffer_overflow_count += 1
                    self.last_error = (
                        "Depth event buffer overflow at stream end; reconnecting for fresh snapshot"
                    )
                    while True:
                        try:
                            event_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    event_queue.put_nowait(None)


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
            event_queue: asyncio.Queue = asyncio.Queue(maxsize=SNAPSHOT_BUFFER_MAX_EVENTS)

            collector_task = asyncio.create_task(
                self._collect_depth_events(websocket, event_queue)
            )

            try:
                snapshot = await self._fetch_snapshot()

                async with self._lock:
                    self._load_snapshot(snapshot)

                # Apply buffered events until the book is synchronized.
                while not self.synchronized:
                    event = await event_queue.get()
                    if event is None:
                        self.last_error = self.last_error or "WebSocket ended before snapshot synchronization"
                        return
                    if collector_task.done():
                        # Buffered events from a closed stream cannot establish
                        # a usable live book, even if one overlaps the snapshot.
                        self.synchronized = False
                        self.synchronized_since = None
                        self.last_error = self.last_error or "WebSocket ended before snapshot synchronization"
                        return

                    if self._event_bridges_snapshot(event):
                        async with self._lock:
                            if not self._apply_snapshot_bridge(
                                event, collector_task=collector_task
                            ):
                                if collector_task.done():
                                    self.last_error = self.last_error or (
                                        "WebSocket ended during snapshot synchronization"
                                    )
                                    return
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
                    event = await event_queue.get()
                    if event is None:
                        self.synchronized = False
                        self.synchronized_since = None
                        self.last_error = self.last_error or "WebSocket stream ended after synchronization"
                        return
                    if collector_task.done() or not self.synchronized:
                        # Collector termination invalidates synchronization before
                        # its sentinel is consumed. Do not apply leftover events
                        # during that race or misclassify termination as a gap.
                        self.synchronized = False
                        self.synchronized_since = None
                        self.last_error = self.last_error or "WebSocket stream ended after synchronization"
                        return

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
    def _parse_snapshot_side(levels: Any, side_name: str) -> dict[float, float]:
        """Validate a REST snapshot side before it can enter the local book."""
        if not isinstance(levels, list):
            raise ValueError(f"Binance snapshot {side_name} must be a list")
        parsed: dict[float, float] = {}
        for row in levels:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                raise ValueError(f"Binance snapshot {side_name} contains a malformed level")
            if isinstance(row[0], bool) or isinstance(row[1], bool):
                raise ValueError(f"Binance snapshot {side_name} contains boolean level values")
            try:
                price, quantity = float(row[0]), float(row[1])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Binance snapshot {side_name} contains nonnumeric levels") from exc
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"Binance snapshot {side_name} contains an invalid price")
            if not math.isfinite(quantity) or quantity < 0:
                raise ValueError(f"Binance snapshot {side_name} contains an invalid quantity")
            if quantity > 0:
                parsed[price] = quantity
        return parsed

    @staticmethod
    def _parse_depth_updates(updates: Any, side_name: str) -> list[tuple[float, float]]:
        """Validate an entire live depth side before any book mutation."""
        if not isinstance(updates, list):
            raise ValueError(f"Binance depth {side_name} updates must be a list")
        parsed: list[tuple[float, float]] = []
        for row in updates:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                raise ValueError(f"Binance depth {side_name} contains a malformed level")
            if isinstance(row[0], bool) or isinstance(row[1], bool):
                raise ValueError(f"Binance depth {side_name} contains boolean level values")
            try:
                price, quantity = float(row[0]), float(row[1])
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"Binance depth {side_name} contains nonnumeric levels") from exc
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"Binance depth {side_name} contains an invalid price")
            if not math.isfinite(quantity) or quantity < 0:
                raise ValueError(f"Binance depth {side_name} contains an invalid quantity")
            parsed.append((price, quantity))
        return parsed

    @staticmethod
    def _apply_parsed_depth_updates(book: dict[float, float], updates: list[tuple[float, float]]) -> None:
        for price, quantity in updates:
            if quantity == 0:
                book.pop(price, None)
            else:
                book[price] = quantity

    def _retain_best_levels(self, levels: dict[float, float], *, highest_first: bool) -> dict[float, float]:
        """Keep only the best configured depth levels, bounding retained book memory."""
        if len(levels) <= self.snapshot_limit:
            return levels
        return dict(sorted(levels.items(), key=lambda item: item[0], reverse=highest_first)[:self.snapshot_limit])

    def _load_snapshot(self, snapshot: dict[str, Any]):
        if not isinstance(snapshot, dict):
            raise ValueError("Binance REST snapshot must be an object")
        update_id = snapshot.get("lastUpdateId")
        if isinstance(update_id, bool) or not isinstance(update_id, int) or update_id < 0:
            raise ValueError("Binance snapshot lastUpdateId must be a nonnegative integer")
        # Validate both sides before replacing the current state, so a bad snapshot
        # cannot leave a partially replaced book.
        bids = self._parse_snapshot_side(snapshot.get("bids", []), "bids")
        asks = self._parse_snapshot_side(snapshot.get("asks", []), "asks")
        if not bids or not asks:
            raise ValueError("Binance snapshot must contain nonempty bid and ask sides")
        if max(bids) >= min(asks):
            raise ValueError("Binance snapshot has a crossed or locked top of book")
        bids = self._retain_best_levels(bids, highest_first=True)
        asks = self._retain_best_levels(asks, highest_first=False)

        self.bids = bids
        self.asks = asks
        self.last_update_id = update_id
        # A validated REST snapshot is itself a fresh book observation. It
        # establishes the freshness baseline even when the first bridge event
        # overlaps the snapshot but carries no newer update ID.
        self.last_book_update_at = time.time()

        self.synchronized = False
        self.snapshot_count += 1
        self.last_error = None

    def _event_bridges_snapshot(
        self,
        event: dict[str, Any],
    ) -> bool:
        """
        Binance depth events contain:
        U = first update ID
        u = final update ID

        The first event after the snapshot must bridge
        the snapshot update ID.
        """

        if self.last_update_id is None:
            return False
        first_update_id = int(event["U"])
        final_update_id = int(event["u"])

        # USD-M Futures differs from Spot: the first accepted event must
        # overlap the REST snapshot's update ID itself (U <= lastUpdateId <= u).
        return (
            first_update_id <= self.last_update_id
            <= final_update_id
        )

    def _apply_event(
        self,
        event: dict[str, Any],
        *,
        validate_previous_sequence: bool = True,
    ) -> bool:
        """
        Apply a depth event.

        Returns False when a sequence gap is detected.
        """

        if self.last_update_id is None:
            return False
        # Live deltas must not mutate a book after collector termination has
        # invalidated synchronization. Snapshot bridge application explicitly
        # bypasses this guard via validate_previous_sequence=False.
        if validate_previous_sequence and not self.synchronized:
            return False

        first_update_id = int(event["U"])
        final_update_id = int(event["u"])

        # Ignore old events.
        if final_update_id <= self.last_update_id:
            return True

        # Snapshot-bridge events are validated by U/u overlap with the REST
        # snapshot. Only events after that bridge enforce pu continuity.
        if validate_previous_sequence:
            previous_final_id = event.get("pu")
            # Futures diff-depth requires pu to prove continuity with the prior
            # WebSocket event. U/u overlap alone is not a substitute after sync.
            if isinstance(previous_final_id, bool) or not isinstance(previous_final_id, (int, str)):
                return False
            try:
                previous_final_id = int(previous_final_id)
            except (TypeError, ValueError):
                return False
            if previous_final_id < 0 or previous_final_id != self.last_update_id:
                return False

        # Validate both sides and apply to copies so malformed or crossed depth
        # events cannot partially mutate the live book.
        try:
            bid_updates = self._parse_depth_updates(event.get("b", []), "bids")
            ask_updates = self._parse_depth_updates(event.get("a", []), "asks")
            if not bid_updates and not ask_updates:
                raise ValueError("Binance depth event contains no level updates")
            next_bids = dict(self.bids)
            next_asks = dict(self.asks)
            self._apply_parsed_depth_updates(next_bids, bid_updates)
            self._apply_parsed_depth_updates(next_asks, ask_updates)
            if not next_bids or not next_asks:
                raise ValueError("Binance depth update would empty one side of the book")
            next_bids = self._retain_best_levels(next_bids, highest_first=True)
            next_asks = self._retain_best_levels(next_asks, highest_first=False)
            if max(next_bids) >= min(next_asks):
                raise ValueError("Binance depth update would cross or lock the book")
        except ValueError:
            self.invalid_depth_message_count += 1
            raise

        self.bids = next_bids
        self.asks = next_asks
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
            "snapshot_limit": self.snapshot_limit,
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
            "invalid_depth_message_count": self.invalid_depth_message_count,
            "snapshot_buffer_overflow_count": self.snapshot_buffer_overflow_count,
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
