import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.market_data.backend_stream import BinanceOrderBookStream


class BinanceOrderBookSynchronizationTests(unittest.TestCase):
    def setUp(self):
        self.stream = BinanceOrderBookStream("BTCUSDT")
        self.stream._load_snapshot({
            "lastUpdateId": 100,
            "bids": [["100.0", "2.0"], ["99.0", "3.0"]],
            "asks": [["101.0", "4.0"], ["102.0", "5.0"]],
        })

    def event(self, first, final, bids=None, asks=None, previous=None):
        event = {"U": first, "u": final, "b": bids or [], "a": asks or []}
        if previous is not None:
            event["pu"] = previous
        return event

    def test_rejects_boolean_and_fractional_live_sequence_ids(self):
        self.stream.last_update_id = 101
        malformed_events = [
            self.event(True, 103, previous=101),
            self.event(102, 103.5, previous=101),
            self.event(102, 103, previous=101.5),
            self.event(102, -1, previous=101),
        ]
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        for event in malformed_events:
            with self.subTest(event=event):
                self.assertFalse(self.stream._apply_event(event))
                self.assertEqual(self.stream.last_update_id, 101)
                self.assertEqual(self.stream.bids, before_bids)
                self.assertEqual(self.stream.asks, before_asks)

    def test_reversed_update_id_range_rejected_without_mutation(self):
        self.stream.last_update_id = 101
        event = self.event(105, 104, bids=[["99.0", "9.0"]], previous=101)
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        self.assertFalse(self.stream._apply_event(event))
        self.assertEqual(self.stream.last_update_id, 101)
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)

    def test_snapshot_update_id_rejects_boolean_fractional_and_negative(self):
        valid_snapshot = {
            "bids": [["100.0", "2.0"]],
            "asks": [["101.0", "4.0"]],
        }
        for invalid_id in (True, 100.5, -1):
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaisesRegex(ValueError, "lastUpdateId"):
                    self.stream._load_snapshot({**valid_snapshot, "lastUpdateId": invalid_id})

    def test_event_covered_by_snapshot_is_not_bridge(self):
        self.assertFalse(self.stream._event_bridges_snapshot(self.event(98, 99)))

    def test_bridge_event_with_next_update_id_is_accepted(self):
        self.assertTrue(self.stream._event_bridges_snapshot(self.event(100, 101)))

    def test_event_starting_after_snapshot_id_is_rejected(self):
        self.assertFalse(self.stream._event_bridges_snapshot(self.event(101, 101)))

    def test_snapshot_id_boundary_is_valid_bridge(self):
        self.assertTrue(self.stream._event_bridges_snapshot(self.event(100, 100)))

    def test_event_starting_after_required_next_id_is_rejected(self):
        self.assertFalse(self.stream._event_bridges_snapshot(self.event(102, 103)))

    def test_event_final_id_before_snapshot_is_rejected(self):
        self.assertFalse(self.stream._event_bridges_snapshot(self.event(95, 99)))

    def test_snapshot_missing_update_id_rejects_bridge(self):
        self.stream.last_update_id = None
        self.assertFalse(self.stream._event_bridges_snapshot(self.event(1, 2)))

    def test_apply_first_bridging_event_updates_book_and_sequence(self):
        e = self.event(100, 101, bids=[["100.0", "0"], ["99.5", "7"]], asks=[["101.0", "6"]], previous=99)
        self.assertTrue(self.stream._event_bridges_snapshot(e))
        self.assertTrue(self.stream._apply_snapshot_bridge(e))
        self.assertEqual(self.stream.last_update_id, 101)
        self.assertNotIn(100.0, self.stream.bids)
        self.assertEqual(self.stream.bids[99.5], 7.0)
        self.assertEqual(self.stream.asks[101.0], 6.0)

    def test_old_event_is_ignored_without_mutating_book(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        self.assertTrue(self.stream._apply_event(self.event(90, 100, bids=[["100.0", "99"]])))
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, 100)

    def test_contiguous_event_with_previous_id_applies(self):
        e = self.event(102, 103, bids=[["100.0", "8"]], previous=101)
        self.stream.last_update_id = 101
        self.assertTrue(self.stream._apply_event(e))
        self.assertEqual(self.stream.last_update_id, 103)
        self.assertEqual(self.stream.bids[100.0], 8.0)

    def test_previous_update_id_gap_forces_resync(self):
        e = self.event(102, 103, bids=[["100.0", "8"]], previous=100)
        self.stream.last_update_id = 101
        self.assertFalse(self.stream._apply_event(e))
        self.assertEqual(self.stream.last_update_id, 101)
        self.assertEqual(self.stream.bids[100.0], 2.0)

    def test_gap_without_previous_update_id_forces_resync(self):
        e = self.event(103, 104, asks=[["101.0", "8"]])
        self.stream.last_update_id = 101
        self.assertFalse(self.stream._apply_event(e))
        self.assertEqual(self.stream.last_update_id, 101)
        self.assertEqual(self.stream.asks[101.0], 4.0)

    def test_live_event_missing_pu_is_rejected_even_if_u_is_contiguous(self):
        e = self.event(102, 103, asks=[["101.0", "0"], ["100.5", "3"]])
        self.stream.last_update_id = 101
        before_asks = dict(self.stream.asks)
        self.assertFalse(self.stream._apply_event(e))
        self.assertEqual(self.stream.last_update_id, 101)
        self.assertEqual(self.stream.asks, before_asks)

    def test_invalid_numeric_update_is_not_silently_applied(self):
        e = self.event(101, 102, bids=[["not-a-price", "2"]], previous=101)
        self.stream.last_update_id = 101
        with self.assertRaises((ValueError, TypeError)):
            self.stream._apply_event(e)

    def test_stale_book_is_not_returned(self):
        self.stream.connected = True
        self.stream.synchronized = True
        self.stream.last_book_update_at = time.time() - 10
        self.assertIsNone(asyncio.run(self.stream.get_order_book()))

    def test_duplicate_event_does_not_refresh_stale_book(self):
        self.stream.connected = True
        self.stream.synchronized = True
        old_progress = time.time() - 10
        self.stream.last_book_update_at = old_progress
        self.assertTrue(self.stream._apply_event(self.event(90, 100)))
        self.assertEqual(self.stream.last_book_update_at, old_progress)
        self.assertIsNone(asyncio.run(self.stream.get_order_book()))

    def test_progressing_event_refreshes_book_and_returns_age(self):
        self.stream.connected = True
        self.stream.synchronized = True
        self.stream.last_book_update_at = None
        event = self.event(101, 101, bids=[["99.5", "1.0"]], previous=100)
        self.assertTrue(self.stream._apply_event(event))
        book = asyncio.run(self.stream.get_order_book())
        self.assertIsNotNone(book)
        self.assertFalse(book["stale"])
        self.assertLessEqual(book["age_seconds"], 3.0)
        self.assertEqual(book["last_update_id"], 101)

    def test_stop_marks_stream_unsynchronized(self):
        self.assertFalse(self.stream.synchronized)
        self.assertIsNotNone(self.stream.last_update_id)


class _L12FakeWebsocket:
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


class _L12FakeConnection:
    def __init__(self, websocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb):
        return False


class BinanceInitialBridgeReconnectTests(unittest.IsolatedAsyncioTestCase):
    def _event(self, U, u, pu=None):
        event = {"U": U, "u": u, "b": [], "a": []}
        if pu is not None:
            event["pu"] = pu
        return event

    def _snapshot(self, update_id, bid_qty=1.0):
        return {
            "lastUpdateId": update_id,
            "bids": [["100.0", str(bid_qty)]],
            "asks": [["101.0", "1.0"]],
        }

    async def _run_two_connection_recovery(self, first_event):
        stream = BinanceOrderBookStream("BTCUSDT")
        original_sleep = asyncio.sleep

        async def fast_sleep(_seconds):
            await original_sleep(0)

        first_ws = _L12FakeWebsocket([first_event])
        second_ws = _L12FakeWebsocket(
            [self._event(200, 201, pu=199)],
            stop_event=stream._stop_event,
        )
        connections = [_L12FakeConnection(first_ws), _L12FakeConnection(second_ws)]
        snapshot_fetch = AsyncMock(side_effect=[
            self._snapshot(100),
            self._snapshot(200, bid_qty=4.0),
        ])
        with patch(
            "app.market_data.backend_stream.websockets.connect",
            side_effect=connections,
        ) as connect_mock, patch.object(
            stream, "_fetch_snapshot", new=snapshot_fetch
        ), patch(
            "app.market_data.backend_stream.asyncio.sleep", new=fast_sleep
        ):
            await asyncio.wait_for(stream._run_forever(), timeout=2.0)

        self.assertEqual(connect_mock.call_count, 2)
        self.assertEqual(snapshot_fetch.await_count, 2)
        self.assertTrue(stream.synchronized)
        self.assertEqual(stream.last_update_id, 201)
        self.assertEqual(stream.bids[100.0], 4.0)

    async def test_closed_websocket_before_snapshot_bridge_reconnects(self):
        await self._run_two_connection_recovery(self._event(98, 99, pu=97))

    async def test_forward_gap_at_snapshot_plus_one_reconnects(self):
        # For Futures, U=L+1 does not satisfy the documented U<=L<=u bridge.
        await self._run_two_connection_recovery(self._event(101, 101, pu=100))


if __name__ == "__main__":
    unittest.main()


# API-level checks for the read-only Layer 1 analysis route.
import asyncio
import pytest
from fastapi import HTTPException
from app.services.imbalance_detector import OrderBookImbalanceDetector
from app import main

class StubUnifiedBooks:
    def __init__(self, book):
        self.book = book
    def get_book(self, exchange, symbol):
        return self.book


def valid_normalized_book():
    return {
        "exchange": "bybit", "symbol": "BTCUSDT",
        "bids": [[100.0, 10.0], [99.9, 8.0]],
        "asks": [[100.1, 2.0], [100.2, 2.0]],
        "synchronized": True, "stale": False, "age_seconds": 0.2,
        "integrity_error": None,
    }


def setup_layer1_api(monkeypatch, book):
    monkeypatch.setattr(main.app.state, "unified_market_data", StubUnifiedBooks(book), raising=False)
    monkeypatch.setattr(main.app.state, "imbalance_detector", OrderBookImbalanceDetector(), raising=False)


def test_layer1_api_valid_book_returns_imbalance(monkeypatch):
    setup_layer1_api(monkeypatch, valid_normalized_book())
    result = asyncio.run(main.analyze_imbalance("bybit", "BTCUSDT", 2))
    assert result["classification"] == "BUY_PRESSURE"
    assert result["metrics"]["weighted_imbalance"] > 0


def test_layer1_api_missing_book_returns_404(monkeypatch):
    setup_layer1_api(monkeypatch, None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.analyze_imbalance("bybit", "BTCUSDT", 10))
    assert exc.value.status_code == 404


def test_layer1_api_invalid_book_returns_422(monkeypatch):
    book = valid_normalized_book()
    book["synchronized"] = False
    setup_layer1_api(monkeypatch, book)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.analyze_imbalance("bybit", "BTCUSDT", 10))
    assert exc.value.status_code == 422


def test_layer1_api_unsupported_exchange_returns_400(monkeypatch):
    setup_layer1_api(monkeypatch, valid_normalized_book())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.analyze_imbalance("unsupported", "BTCUSDT", 10))
    assert exc.value.status_code == 400
