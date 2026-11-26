import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.market_data.backend_stream import BinanceOrderBookStream


def depth_event(U, u, pu=None, bids=None, asks=None):
    event = {"U": U, "u": u, "b": bids or [], "a": asks or []}
    if pu is not None:
        event["pu"] = pu
    return event


def snapshot(update_id, bid_quantity=1.0):
    return {
        "lastUpdateId": update_id,
        "bids": [["100.0", str(bid_quantity)]],
        "asks": [["101.0", "1.0"]],
    }


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


class Layer1SnapshotBridgeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_futures_snapshot_bridge_ignores_pu_and_applies_book(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        ws = FakeWebsocket(
            [depth_event(100, 101, pu=98, bids=[["100.0", "2.5"]])],
            stop_event=stream._stop_event,
        )
        snapshot_fetch = AsyncMock(return_value=snapshot(100))
        with (
            patch("app.market_data.backend_stream.websockets.connect", return_value=FakeConnection(ws)),
            patch.object(stream, "_fetch_snapshot", new=snapshot_fetch),
        ):
            await stream._connect_and_sync()

        self.assertTrue(stream.synchronized)
        self.assertEqual(stream.last_update_id, 101)
        self.assertEqual(stream.bids[100.0], 2.5)
        self.assertEqual(snapshot_fetch.await_count, 1)

    async def test_closed_stream_before_snapshot_bridge_raises_not_hangs(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        ws = FakeWebsocket([])
        snapshot_fetch = AsyncMock(return_value=snapshot(100))
        with (
            patch("app.market_data.backend_stream.websockets.connect", return_value=FakeConnection(ws)),
            patch.object(stream, "_fetch_snapshot", new=snapshot_fetch),
        ):
            with self.assertRaisesRegex(ConnectionError, "closed"):
                await asyncio.wait_for(stream._connect_and_sync(), timeout=1.0)

        self.assertFalse(stream.synchronized)
        self.assertEqual(snapshot_fetch.await_count, 1)

    async def test_malformed_bridge_update_does_not_mutate_snapshot(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        ws = FakeWebsocket(
            [depth_event(100, 101, pu=98, bids=[["bad-price", "2.0"]])],
            stop_event=stream._stop_event,
        )
        snapshot_fetch = AsyncMock(return_value=snapshot(100, bid_quantity=1.0))
        with (
            patch("app.market_data.backend_stream.websockets.connect", return_value=FakeConnection(ws)),
            patch.object(stream, "_fetch_snapshot", new=snapshot_fetch),
        ):
            await stream._connect_and_sync()

        self.assertFalse(stream.synchronized)
        self.assertEqual(stream.last_update_id, 100)
        self.assertEqual(stream.bids[100.0], 1.0)
        self.assertEqual(stream.sequence_gap_count, 1)

    async def test_initial_gap_recovers_with_fresh_snapshot(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        original_sleep = asyncio.sleep

        async def fast_sleep(_seconds):
            await original_sleep(0)

        first = FakeWebsocket([depth_event(101, 102, pu=100, bids=[["100.0", "9.0"]])])
        second = FakeWebsocket(
            [depth_event(200, 201, pu=199, bids=[["100.0", "4.0"]])],
            stop_event=stream._stop_event,
        )
        connections = [FakeConnection(first), FakeConnection(second)]
        snapshot_fetch = AsyncMock(side_effect=[snapshot(100), snapshot(200)])
        with (
            patch("app.market_data.backend_stream.websockets.connect", side_effect=connections) as connect_mock,
            patch.object(stream, "_fetch_snapshot", new=snapshot_fetch),
            patch("app.market_data.backend_stream.asyncio.sleep", new=fast_sleep),
        ):
            await asyncio.wait_for(stream._run_forever(), timeout=2.0)

        self.assertEqual(connect_mock.call_count, 2)
        self.assertEqual(snapshot_fetch.await_count, 2)
        self.assertEqual(stream.last_update_id, 201)
        self.assertEqual(stream.bids[100.0], 4.0)
        self.assertTrue(stream.connected)
        self.assertTrue(stream.synchronized)
        self.assertEqual(stream.sequence_gap_count, 0)

    async def test_closed_stream_after_sync_reconnects_with_fresh_snapshot(self):
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
        snapshot_fetch = AsyncMock(side_effect=[snapshot(100), snapshot(200)])
        with (
            patch("app.market_data.backend_stream.websockets.connect", side_effect=connections) as connect_mock,
            patch.object(stream, "_fetch_snapshot", new=snapshot_fetch),
            patch("app.market_data.backend_stream.asyncio.sleep", new=fast_sleep),
        ):
            await asyncio.wait_for(stream._run_forever(), timeout=2.0)

        self.assertEqual(connect_mock.call_count, 2)
        self.assertEqual(snapshot_fetch.await_count, 2)
        self.assertEqual(stream.last_update_id, 201)
        self.assertEqual(stream.bids[100.0], 4.0)
        self.assertTrue(stream.connected)
        self.assertTrue(stream.synchronized)


if __name__ == "__main__":
    unittest.main()
