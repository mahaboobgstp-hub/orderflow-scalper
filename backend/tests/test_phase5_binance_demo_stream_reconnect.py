import asyncio
import json
import unittest
import time
from unittest.mock import AsyncMock, patch

from app.market_data.backend_stream import BinanceOrderBookStream


def depth_event(U, u, pu=None, bids=None, asks=None):
    event = {"U": U, "u": u, "b": bids or [], "a": asks or []}
    if pu is not None:
        event["pu"] = pu
    return event


class FakeWebsocket:
    def __init__(self, events, stop_event=None):
        self.events = events
        self.stop_event = stop_event

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self.events:
            await asyncio.sleep(0)
            yield json.dumps(event)
        if self.stop_event is not None:
            self.stop_event.set()


class FakeConnection:
    def __init__(self, websocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb):
        return False


def snapshot(update_id, bid_quantity=1.0):
    return {
        "lastUpdateId": update_id,
        "bids": [["100.0", str(bid_quantity)]],
        "asks": [["101.0", "1.0"]],
    }


class BinanceStreamReconnectTests(unittest.IsolatedAsyncioTestCase):
    def first_connection_events(self):
        return [
            depth_event(100, 101, pu=98, bids=[["100.0", "2.0"]]),
            depth_event(102, 103, pu=101, bids=[["100.0", "3.0"]]),
            depth_event(104, 105, pu=999, bids=[["100.0", "9.0"]]),
        ]

    async def test_gap_invalidates_book_immediately_and_read_returns_none(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        stream.connected = True
        stream.synchronized = True
        websocket = FakeWebsocket(self.first_connection_events())
        with patch("app.market_data.backend_stream.websockets.connect", return_value=FakeConnection(websocket)), \
             patch.object(stream, "_fetch_snapshot", new=AsyncMock(return_value=snapshot(100))):
            await stream._connect_and_sync()

        self.assertFalse(stream.connected)
        self.assertFalse(stream.synchronized)
        self.assertEqual(stream.last_update_id, 103)
        self.assertEqual(stream.bids[100.0], 3.0)
        self.assertEqual(stream.last_error, "Order-book sequence gap detected")
        self.assertIsNone(await stream.get_order_book())

    async def test_run_forever_recovers_after_gap_using_new_snapshot(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        first = FakeWebsocket(self.first_connection_events())
        second = FakeWebsocket(
            [depth_event(200, 201, pu=199, bids=[["100.0", "4.0"]])],
            stop_event=stream._stop_event,
        )
        connections = [FakeConnection(first), FakeConnection(second)]
        with patch("app.market_data.backend_stream.websockets.connect", side_effect=connections) as mock_connect, \
             patch.object(stream, "_fetch_snapshot", new=AsyncMock(side_effect=[snapshot(100), snapshot(200)])):
            await stream._run_forever()

        self.assertEqual(mock_connect.call_count, 2)
        # _run_forever clears connection/sync flags after its stop event,
        # but the recovered snapshot must have been applied before shutdown.
        self.assertFalse(stream.connected)
        self.assertFalse(stream.synchronized)
        self.assertEqual(stream.last_update_id, 201)
        self.assertEqual(stream.bids[100.0], 4.0)
        self.assertIsNone(stream.last_error)



    async def test_initial_snapshot_bridge_gap_reconnects_with_fresh_snapshot(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        original_sleep = asyncio.sleep

        async def fast_sleep(_seconds):
            await original_sleep(0)

        first = FakeWebsocket([
            depth_event(102, 103, pu=101, bids=[["100.0", "9.0"]]),
        ])
        second = FakeWebsocket(
            [depth_event(200, 201, pu=199, bids=[["100.0", "4.0"]])],
            stop_event=stream._stop_event,
        )
        connections = [FakeConnection(first), FakeConnection(second)]
        snapshot_fetch = AsyncMock(side_effect=[snapshot(100), snapshot(200)])
        with patch("app.market_data.backend_stream.websockets.connect", side_effect=connections) as mock_connect, \
             patch.object(stream, "_fetch_snapshot", new=snapshot_fetch), \
             patch("app.market_data.backend_stream.asyncio.sleep", new=fast_sleep):
            await stream._run_forever()

        self.assertEqual(mock_connect.call_count, 2)
        self.assertEqual(snapshot_fetch.await_count, 2)
        # The initial forward gap forces a new snapshot. The second connection
        # bridges snapshot 200 and applies update 201 before shutdown.
        self.assertEqual(stream.last_update_id, 201)
        self.assertEqual(stream.bids[100.0], 4.0)
        self.assertIsNone(stream.last_error)

    async def test_closed_websocket_reconnects_after_synchronization(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        original_sleep = asyncio.sleep

        async def fast_sleep(_seconds):
            await original_sleep(0)

        first = FakeWebsocket([
            depth_event(100, 101, pu=98, bids=[["100.0", "2.0"]]),
            depth_event(102, 103, pu=101, bids=[["100.0", "3.0"]]),
        ])
        second = FakeWebsocket(
            [depth_event(200, 201, pu=199, bids=[["100.0", "4.0"]])],
            stop_event=stream._stop_event,
        )
        connections = [FakeConnection(first), FakeConnection(second)]
        with patch("app.market_data.backend_stream.websockets.connect", side_effect=connections) as mock_connect, \
             patch.object(stream, "_fetch_snapshot", new=AsyncMock(side_effect=[snapshot(100), snapshot(200)])), \
             patch("app.market_data.backend_stream.asyncio.sleep", new=fast_sleep):
            await stream._run_forever()

        self.assertEqual(mock_connect.call_count, 2)
        self.assertEqual(stream.last_update_id, 201)
        self.assertEqual(stream.bids[100.0], 4.0)
        self.assertIsNone(stream.last_error)
        self.assertIsNone(await stream.get_order_book())


    async def test_fresh_book_is_returned_with_age_metadata(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        stream.connected = True
        stream.synchronized = True
        stream.last_update_id = 100
        stream.bids = {100.0: 2.0}
        stream.asks = {101.0: 2.0}
        stream._last_event_received_at = time.monotonic() - 0.25

        result = await stream.get_order_book()
        status = await stream.get_status()
        self.assertIsNotNone(result)
        self.assertLessEqual(result["age_seconds"], 3.0)
        self.assertFalse(result["stale"])
        self.assertFalse(status["stale"])

    async def test_stale_synchronized_book_is_rejected(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        stream.connected = True
        stream.synchronized = True
        stream.last_update_id = 100
        stream.bids = {100.0: 2.0}
        stream.asks = {101.0: 2.0}
        stream._last_event_received_at = time.monotonic() - 4.0

        result = await stream.get_order_book()
        status = await stream.get_status()
        self.assertIsNone(result)
        self.assertTrue(status["stale"])
        self.assertGreater(status["last_event_age_seconds"], 3.0)

if __name__ == "__main__":
    unittest.main()
