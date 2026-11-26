import asyncio
import time
import unittest
from unittest.mock import patch

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

    def test_overlapping_event_without_previous_id_is_applied(self):
        e = self.event(101, 102, asks=[["101.0", "0"], ["100.5", "3"]])
        self.stream.last_update_id = 101
        self.assertTrue(self.stream._apply_event(e))
        self.assertEqual(self.stream.last_update_id, 102)
        self.assertNotIn(101.0, self.stream.asks)
        self.assertEqual(self.stream.asks[100.5], 3.0)

    def test_invalid_numeric_update_is_not_silently_applied(self):
        e = self.event(101, 102, bids=[["not-a-price", "2"]])
        self.stream.last_update_id = 101
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        self.assertFalse(self.stream._apply_event(e))
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, 101)

    def test_stale_book_is_not_returned(self):
        self.stream.connected = True
        self.stream.synchronized = True
        self.stream.last_book_update_at = time.time() - 10
        self.stream.last_book_update_monotonic = time.monotonic() - 10
        self.assertIsNone(asyncio.run(self.stream.get_order_book()))

    def test_duplicate_event_does_not_refresh_stale_book(self):
        self.stream.connected = True
        self.stream.synchronized = True
        old_progress = time.time() - 10
        self.stream.last_book_update_at = old_progress
        self.stream.last_book_update_monotonic = time.monotonic() - 10
        self.assertTrue(self.stream._apply_event(self.event(90, 100)))
        self.assertEqual(self.stream.last_book_update_at, old_progress)
        self.assertIsNone(asyncio.run(self.stream.get_order_book()))

    def test_progressing_event_refreshes_book_and_returns_age(self):
        self.stream.connected = True
        self.stream.synchronized = True
        self.stream.last_book_update_at = None
        self.stream.last_book_update_monotonic = None
        event = self.event(101, 101, bids=[["99.5", "1.0"]])
        self.assertTrue(self.stream._apply_event(event))
        book = asyncio.run(self.stream.get_order_book())
        self.assertIsNotNone(book)
        self.assertFalse(book["stale"])
        self.assertLessEqual(book["age_seconds"], 3.0)
        self.assertEqual(book["last_update_id"], 101)

    def test_snapshot_rejects_invalid_nonfinite_and_crossed_books(self):
        invalid_snapshots = [
            {"lastUpdateId": 101, "bids": [["bad", "1"]], "asks": [["101", "1"]]},
            {"lastUpdateId": 101, "bids": [["100", "nan"]], "asks": [["101", "1"]]},
            {"lastUpdateId": 101, "bids": [["102", "1"]], "asks": [["101", "1"]]},
            {"lastUpdateId": 101, "bids": [["100", "1"]], "asks": [["100", "1"]]},
            {"lastUpdateId": True, "bids": [["100", "1"]], "asks": [["101", "1"]]},
        ]
        for snapshot in invalid_snapshots:
            with self.subTest(snapshot=snapshot):
                with self.assertRaises(ValueError):
                    self.stream._load_snapshot(snapshot)

    def test_sequence_ids_reject_bool_fractional_and_reversed_values(self):
        invalid_events = [
            {"U": True, "u": 102, "b": [], "a": []},
            {"U": 101, "u": 102.5, "b": [], "a": []},
            {"U": 103, "u": 102, "b": [], "a": []},
            {"U": 101, "u": 102, "pu": False, "b": [], "a": []},
        ]
        self.stream.last_update_id = 101
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        for event in invalid_events:
            with self.subTest(event=event):
                self.assertFalse(self.stream._apply_event(event))
                self.assertEqual(self.stream.bids, before_bids)
                self.assertEqual(self.stream.asks, before_asks)
                self.assertEqual(self.stream.last_update_id, 101)

    def test_crossing_event_is_rejected_transactionally(self):
        self.stream.last_update_id = 101
        event = self.event(102, 102, bids=[["102.0", "2.0"]])
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        self.assertFalse(self.stream._apply_event(event))
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, 101)

    def test_monotonic_freshness_is_not_affected_by_wall_clock_jump(self):
        self.stream.connected = True
        self.stream.synchronized = True
        self.stream.last_update_id = 101
        self.stream.last_book_update_monotonic = time.monotonic() - 0.25
        with patch("app.market_data.backend_stream.time.time", return_value=1.0):
            book = asyncio.run(self.stream.get_order_book())
            status = asyncio.run(self.stream.get_status())
        self.assertIsNotNone(book)
        self.assertFalse(status["stale"])
        self.assertLess(book["age_seconds"], 1.0)

    def test_stale_monotonic_book_is_rejected(self):
        self.stream.connected = True
        self.stream.synchronized = True
        self.stream.last_update_id = 101
        self.stream.last_book_update_monotonic = time.monotonic() - 10.0
        self.assertIsNone(asyncio.run(self.stream.get_order_book()))

    def test_futures_snapshot_bridge_requires_snapshot_id_overlap(self):
        self.assertTrue(self.stream._event_bridges_snapshot(self.event(100, 100)))
        self.assertTrue(self.stream._event_bridges_snapshot(self.event(99, 100)))
        self.assertTrue(self.stream._event_bridges_snapshot(self.event(99, 101)))
        self.assertFalse(self.stream._event_bridges_snapshot(self.event(101, 101)))
        self.assertTrue(self.stream._snapshot_bridge_gap(self.event(101, 102)))
        self.assertFalse(self.stream._snapshot_bridge_gap(self.event(100, 101)))
        self.assertFalse(self.stream._snapshot_bridge_gap(self.event(99, 99)))

    def test_stop_marks_stream_unsynchronized(self):
        self.assertFalse(self.stream.synchronized)
        self.assertIsNotNone(self.stream.last_update_id)


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
