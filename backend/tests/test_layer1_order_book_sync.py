import asyncio
import time
import unittest

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
        self.stream.synchronized = True
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        self.assertTrue(self.stream._apply_event(self.event(90, 100, bids=[["100.0", "99"]])))
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, 100)

    def test_contiguous_event_with_previous_id_applies(self):
        e = self.event(102, 103, bids=[["100.0", "8"]], previous=101)
        self.stream.last_update_id = 101
        self.stream.synchronized = True
        self.assertTrue(self.stream._apply_event(e))
        self.assertEqual(self.stream.last_update_id, 103)
        self.assertEqual(self.stream.bids[100.0], 8.0)

    def test_previous_update_id_gap_forces_resync(self):
        e = self.event(102, 103, bids=[["100.0", "8"]], previous=100)
        self.stream.last_update_id = 101
        self.stream.synchronized = True
        self.assertFalse(self.stream._apply_event(e))
        self.assertEqual(self.stream.last_update_id, 101)
        self.assertEqual(self.stream.bids[100.0], 2.0)

    def test_gap_without_previous_update_id_forces_resync(self):
        e = self.event(103, 104, asks=[["101.0", "8"]])
        self.stream.last_update_id = 101
        self.stream.synchronized = True
        self.assertFalse(self.stream._apply_event(e))
        self.assertEqual(self.stream.last_update_id, 101)
        self.assertEqual(self.stream.asks[101.0], 4.0)

    def test_overlapping_event_without_previous_id_forces_resync(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        e = self.event(101, 102, asks=[["101.0", "0"], ["100.5", "3"]])
        self.stream.last_update_id = 101
        self.stream.synchronized = True
        self.assertFalse(self.stream._apply_event(e))
        self.assertEqual(self.stream.last_update_id, 101)
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)

    def test_invalid_numeric_update_is_not_silently_applied(self):
        e = self.event(101, 102, bids=[["not-a-price", "2"]], previous=101)
        self.stream.last_update_id = 101
        self.stream.synchronized = True
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

    def test_primary_connection_session_duration_is_retained_after_disconnect(self):
        self.stream._record_connection_success(now=100.0)
        self.stream._record_disconnect("network_closed", now=112.25)
        self.assertFalse(self.stream.connected)
        self.assertIsNone(self.stream.connected_at)
        self.assertEqual(self.stream.last_connection_duration_seconds, 12.25)

        # A second disconnect without a live session must not overwrite the
        # completed session duration.
        self.stream._record_disconnect("stop_requested", now=130.0)
        self.assertEqual(self.stream.last_connection_duration_seconds, 12.25)

        self.stream._record_connection_success(now=200.0)
        self.stream._record_disconnect("reconnect_closed", now=205.0)
        self.assertEqual(self.stream.last_connection_duration_seconds, 5.0)
        status = asyncio.run(self.stream.get_status())
        self.assertIsNone(status["connected_duration_seconds"])
        self.assertEqual(status["last_connection_duration_seconds"], 5.0)


    def test_stop_preserves_actual_disconnect_reason_and_timestamp(self):
        self.stream._record_disconnect("sequence_gap", now=123.0)
        self.stream.last_connection_duration_seconds = 6.5

        asyncio.run(self.stream.stop())

        self.assertFalse(self.stream.connected)
        self.assertFalse(self.stream.synchronized)
        self.assertIsNone(self.stream.synchronized_since)
        self.assertEqual(self.stream.last_disconnect_reason, "sequence_gap")
        self.assertEqual(self.stream.last_disconnect_at, 123.0)
        self.assertEqual(self.stream.last_connection_duration_seconds, 6.5)

    def test_stop_records_disconnect_for_active_session(self):
        self.stream._record_connection_success(now=time.time() - 5.0)

        asyncio.run(self.stream.stop())

        self.assertFalse(self.stream.connected)
        self.assertIsNone(self.stream.connected_at)
        self.assertEqual(self.stream.last_disconnect_reason, "stop_requested")
        self.assertIsNotNone(self.stream.last_disconnect_at)
        self.assertGreaterEqual(self.stream.last_connection_duration_seconds, 5.0)

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
