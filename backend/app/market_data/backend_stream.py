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


class BinanceOrderBookStream:
    def __init__(
        self,
        symbol: str = "BTCUSDT",
        snapshot_limit: int = 1000,
        max_book_age_seconds: float = 3.0,
    ):
        max_age = float(max_book_age_seconds)
        if not math.isfinite(max_age):
            raise ValueError("Maximum book age must be finite.")
        self.max_book_age_seconds = max(0.1, max_age)
        self._last_event_received_at: float | None = None
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
            self._last_event_received_at = None

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
                # Drain buffered updates before interpreting a finished collector
                # as a disconnect; otherwise a closed stream can strand sync.
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

                    if self._event_bridges_snapshot(event):
                        async with self._lock:
                            applied = self._apply_event(
                                event,
                                initial_snapshot_bridge=True,
                            )

                        # Synchronization is valid only if the bridge event
                        # was actually applied to the snapshot.
                        if applied:
                            self.synchronized = True

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
                            # Invalidate immediately so read-only endpoints cannot
                            # serve the last book while reconnecting.
                            self.synchronized = False
                            self.connected = False
                            self.last_error = "Order-book sequence gap detected"
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
    def _parse_snapshot_levels(raw: Any) -> dict[float, float]:
        if not isinstance(raw, list):
            raise ValueError("Snapshot levels must be a list.")
        parsed: dict[float, float] = {}
        for row in raw:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                raise ValueError("Snapshot contains a malformed level.")
            try:
                price, quantity = float(row[0]), float(row[1])
            except (TypeError, ValueError, OverflowError):
                raise ValueError("Snapshot contains a nonnumeric level.") from None
            if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0:
                raise ValueError("Snapshot contains a nonfinite or nonpositive level.")
            parsed[price] = quantity
        return parsed

    @staticmethod
    def _validate_event_levels(raw: Any) -> bool:
        if not isinstance(raw, (list, tuple)):
            return False
        for row in raw:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                return False
            try:
                price, quantity = float(row[0]), float(row[1])
            except (TypeError, ValueError, OverflowError):
                return False
            # Zero quantity is a valid deletion; negative or nonfinite values are not.
            if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity < 0:
                return False
        return True

    @staticmethod
    def _book_integrity_valid(bids: dict[float, float], asks: dict[float, float]) -> bool:
        if not bids or not asks:
            return False
        if any(not math.isfinite(p) or not math.isfinite(q) or p <= 0 or q <= 0 for p, q in bids.items()):
            return False
        if any(not math.isfinite(p) or not math.isfinite(q) or p <= 0 or q <= 0 for p, q in asks.items()):
            return False
        return max(bids) < min(asks)

    def _load_snapshot(self, snapshot: dict[str, Any]):
        if not isinstance(snapshot, dict):
            raise ValueError("Snapshot must be an object.")
        bids = self._parse_snapshot_levels(snapshot.get("bids", []))
        asks = self._parse_snapshot_levels(snapshot.get("asks", []))
        try:
            update_id = int(snapshot["lastUpdateId"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("Snapshot update ID is invalid.") from None
        if not self._book_integrity_valid(bids, asks):
            raise ValueError("Snapshot book is empty, invalid, crossed, or locked.")
        self.bids = bids
        self.asks = asks
        self.last_update_id = update_id
        self.synchronized = False

    @staticmethod
    def _parse_update_id(value: Any) -> int | None:
        """Accept only nonnegative integer sequence IDs, never truncating floats."""
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str):
            value = value.strip()
            if not value or not value.isascii() or not value.isdigit():
                return None
            try:
                return int(value)
            except (ValueError, OverflowError):
                return None
        return None

    def _event_bridges_snapshot(
        self,
        event: dict[str, Any],
    ) -> bool:
        """
        Validate Binance Futures snapshot-to-stream synchronization.

        The first accepted event must cover snapshot lastUpdateId + 1:
        U <= lastUpdateId + 1 <= u. Events fully covered by the snapshot
        are ignored.
        """
        if self.last_update_id is None:
            return False

        if not isinstance(event, dict):
            return False
        first_update_id = self._parse_update_id(event.get("U"))
        final_update_id = self._parse_update_id(event.get("u"))
        if first_update_id is None or final_update_id is None:
            return False

        if first_update_id > final_update_id:
            return False

        bridge_update_id = self.last_update_id + 1
        return (
            final_update_id >= bridge_update_id
            and first_update_id <= bridge_update_id
        )

    def _apply_event(
        self,
        event: dict[str, Any],
        initial_snapshot_bridge: bool = False,
    ) -> bool:
        """
        Apply a depth event.

        The first snapshot-bridging event is validated using U/u only; its
        pu value describes the WebSocket stream's prior event and must not
        be compared to the REST snapshot ID. Subsequent events use pu
        continuity (or U/u continuity when pu is absent).
        Returns False when a sequence gap or malformed sequence is detected.
        """
        if self.last_update_id is None:
            return False

        try:
            first_update_id = int(event["U"])
            final_update_id = int(event["u"])
        except (KeyError, TypeError, ValueError):
            return False

        if first_update_id > final_update_id:
            return False

        if initial_snapshot_bridge:
            # A bridge event must cover the first update after the snapshot;
            # even an event ending at the snapshot ID is not a bridge.
            if not self._event_bridges_snapshot(event):
                return False
        else:
            # Ignore old/duplicate events only after initial sync.
            if final_update_id <= self.last_update_id:
                return True

            # For subsequent Futures depth events, pu must match the
            # previous final update ID. If pu is absent, use the U/u gap
            # rule as a defensive fallback.
            previous_final_id = event.get("pu")
            if previous_final_id is not None:
                parsed_previous_final_id = self._parse_update_id(previous_final_id)
                if parsed_previous_final_id is None or parsed_previous_final_id != self.last_update_id:
                    return False
            elif first_update_id > self.last_update_id + 1:
                return False

        bid_updates = event.get("b", [])
        ask_updates = event.get("a", [])
        if not self._validate_event_levels(bid_updates) or not self._validate_event_levels(ask_updates):
            return False

        # Apply on copies so a malformed update or a crossed result cannot
        # partially mutate the synchronized book before rejection.
        new_bids = dict(self.bids)
        new_asks = dict(self.asks)
        self._update_levels(new_bids, bid_updates)
        self._update_levels(new_asks, ask_updates)
        if not self._book_integrity_valid(new_bids, new_asks):
            return False
        self.bids = new_bids
        self.asks = new_asks
        self.last_update_id = final_update_id
        # Freshness tracks sequence progress, not merely event receipt. Ignored
        # duplicates/old updates must not keep a stalled book marked fresh.
        self._last_event_received_at = time.monotonic()

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
        age_seconds = (
            time.monotonic() - self._last_event_received_at
            if self._last_event_received_at is not None
            else None
        )
        stale = (
            not self.connected
            or not self.synchronized
            or age_seconds is None
            or age_seconds > self.max_book_age_seconds
        )
        return {
            "symbol": self.symbol,
            "connected": self.connected,
            "synchronized": self.synchronized,
            "last_update_id": self.last_update_id,
            "last_event_age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
            "max_book_age_seconds": self.max_book_age_seconds,
            "stale": stale,
            "last_error": self.last_error,
        }

    async def get_order_book(
        self,
        depth: int = 20,
    ) -> dict[str, Any] | None:

        async with self._lock:
            age_seconds = (
                time.monotonic() - self._last_event_received_at
                if self._last_event_received_at is not None
                else None
            )
            if (
                not self.connected
                or not self.synchronized
                or self.last_update_id is None
                or age_seconds is None
                or age_seconds > self.max_book_age_seconds
                or not self._book_integrity_valid(self.bids, self.asks)
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
