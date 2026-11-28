import asyncio
import unittest
from unittest.mock import patch

from app.market_data.backend_stream import BinanceOrderBookStream


class BinanceDepthEventIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.stream = BinanceOrderBookStream("BTCUSDT")
        self.stream._load_snapshot({
            "lastUpdateId": 100,
            "bids": [["100", "2"], ["99", "3"]],
            "asks": [["101", "4"], ["102", "5"]],
        })
        # The fixtures below exercise live deltas against a valid synchronized
        # session unless a test explicitly invalidates synchronization.
        self.stream.synchronized = True


    def test_live_delta_is_refused_after_sync_invalidation_without_mutation(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        before_update_id = self.stream.last_update_id
        before_book_update_at = self.stream.last_book_update_at
        self.stream.synchronized = False
        event = {
            "U": 101, "u": 102, "pu": 100,
            "b": [["99.5", "7"]], "a": [],
        }
        self.assertFalse(self.stream._apply_event(event))
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, before_update_id)
        self.assertEqual(self.stream.last_book_update_at, before_book_update_at)
        self.assertEqual(self.stream.invalid_depth_message_count, 0)

    def test_valid_snapshot_establishes_book_freshness_timestamp(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        with patch("app.market_data.backend_stream.time.time", return_value=1000.0):
            stream._load_snapshot({
                "lastUpdateId": 100,
                "bids": [["100", "2"]],
                "asks": [["101", "3"]],
            })
        self.assertEqual(stream.last_book_update_at, 1000.0)

    def test_snapshot_bridge_without_newer_update_uses_snapshot_freshness(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        snapshot = {
            "lastUpdateId": 100,
            "bids": [["100", "2"]],
            "asks": [["101", "3"]],
        }
        bridge = {"U": 99, "u": 100, "pu": 98, "b": [], "a": []}
        with patch("app.market_data.backend_stream.time.time", return_value=1000.0), patch(
            "app.market_data.backend_stream.time.monotonic", return_value=10.0
        ):
            stream._record_connection_success()
            stream._load_snapshot(snapshot)
            self.assertTrue(stream._apply_snapshot_bridge(bridge))
        self.assertTrue(stream.synchronized)
        with patch("app.market_data.backend_stream.time.time", return_value=1002.0), patch(
            "app.market_data.backend_stream.time.monotonic", return_value=12.0
        ):
            status = asyncio.run(stream.get_status())
            book = asyncio.run(stream.get_order_book())
        self.assertTrue(status["healthy"])
        self.assertFalse(status["stale"])
        self.assertEqual(status["last_book_update_age_seconds"], 2.0)
        self.assertIsNotNone(book)
        self.assertEqual(book["age_seconds"], 2.0)
        with patch("app.market_data.backend_stream.time.time", return_value=1004.1), patch(
            "app.market_data.backend_stream.time.monotonic", return_value=14.1
        ):
            expired = asyncio.run(stream.get_status())
            self.assertTrue(expired["stale"])
            self.assertIsNone(asyncio.run(stream.get_order_book()))

    def test_snapshot_limit_rejects_invalid_values(self):
        invalid_limits = (0, -1, 4, 25, 1001, True, False, 1000.0, "1000", None)
        for invalid in invalid_limits:
            with self.subTest(limit=invalid):
                with self.assertRaises(ValueError):
                    BinanceOrderBookStream(snapshot_limit=invalid)
        for valid in (5, 10, 20, 50, 100, 500, 1000):
            self.assertEqual(BinanceOrderBookStream(snapshot_limit=valid).snapshot_limit, valid)

    def test_snapshot_and_live_updates_retain_best_levels_within_cap(self):
        stream = BinanceOrderBookStream("BTCUSDT", snapshot_limit=5)
        stream._load_snapshot({
            "lastUpdateId": 100,
            "bids": [[str(price), "1"] for price in (100, 99, 98, 97, 96, 95, 94)],
            "asks": [[str(price), "1"] for price in (101, 102, 103, 104, 105, 106, 107)],
        })
        stream.synchronized = True
        self.assertEqual(sorted(stream.bids, reverse=True), [100, 99, 98, 97, 96])
        self.assertEqual(sorted(stream.asks), [101, 102, 103, 104, 105])
        self.assertEqual(len(stream.bids), 5)
        self.assertEqual(len(stream.asks), 5)

        self.assertTrue(stream._apply_event({
            "U": 101, "u": 102, "pu": 100,
            "b": [["100.5", "1"], ["95", "2"]],
            "a": [["100.9", "2"], ["105.5", "1"]],
        }))
        self.assertEqual(sorted(stream.bids, reverse=True), [100.5, 100, 99, 98, 97])
        self.assertEqual(sorted(stream.asks), [100.9, 101, 102, 103, 104])
        self.assertEqual(len(stream.bids), 5)
        self.assertEqual(len(stream.asks), 5)


    def test_crossed_snapshot_is_rejected_without_replacing_existing_book(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        before_update_id = self.stream.last_update_id
        with self.assertRaisesRegex(ValueError, "crossed or locked"):
            self.stream._load_snapshot({
                "lastUpdateId": 200,
                "bids": [["102", "1"]],
                "asks": [["101", "1"]],
            })
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, before_update_id)
        self.assertEqual(self.stream.snapshot_count, 1)

    def test_invalid_ask_payload_does_not_partially_apply_valid_bid(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        before_update_id = self.stream.last_update_id
        event = {
            "U": 101, "u": 102, "pu": 100,
            "b": [["99.5", "7"]],
            "a": [["NaN", "2"]],
        }
        with self.assertRaisesRegex(ValueError, "invalid price"):
            self.stream._apply_event(event)
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, before_update_id)

    def test_crossed_depth_event_is_rejected_atomically(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        before_update_id = self.stream.last_update_id
        event = {
            "U": 101, "u": 102, "pu": 100,
            "b": [["102", "1"]],
            "a": [["101", "1"]],
        }
        with self.assertRaisesRegex(ValueError, "cross or lock"):
            self.stream._apply_event(event)
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, before_update_id)

    def test_boolean_depth_values_are_rejected_without_mutation(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        before_update_id = self.stream.last_update_id
        invalid_events = (
            {"U": 101, "u": 102, "pu": 100, "b": [[True, "1"]], "a": []},
            {"U": 101, "u": 102, "pu": 100, "b": [["99", True]], "a": []},
            {"U": 101, "u": 102, "pu": 100, "b": [], "a": [["101", False]]},
        )
        for event in invalid_events:
            with self.subTest(event=event):
                with self.assertRaisesRegex(ValueError, "boolean level values"):
                    self.stream._apply_event(event)
                self.assertEqual(self.stream.bids, before_bids)
                self.assertEqual(self.stream.asks, before_asks)
                self.assertEqual(self.stream.last_update_id, before_update_id)

    def test_empty_depth_event_is_rejected_without_mutation_and_counted(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        before_update_id = self.stream.last_update_id
        with self.assertRaisesRegex(ValueError, "no level updates"):
            self.stream._apply_event({"U": 101, "u": 102, "pu": 100, "b": [], "a": []})
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, before_update_id)
        self.assertEqual(self.stream.invalid_depth_message_count, 1)

    def test_one_sided_depth_event_is_valid_and_counted_as_applied(self):
        before_asks = dict(self.stream.asks)
        self.assertTrue(self.stream._apply_event({"U": 101, "u": 102, "pu": 100, "b": [["99.5", "7"]], "a": []}))
        self.assertEqual(self.stream.bids[99.5], 7.0)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.invalid_depth_message_count, 0)

    def test_valid_two_sided_depth_event_applies_atomically(self):
        event = {
            "U": 101, "u": 102, "pu": 100,
            "b": [["100", "0"], ["99.5", "7"]],
            "a": [["101", "0"], ["100.5", "6"]],
        }
        self.assertTrue(self.stream._apply_event(event))
        self.assertNotIn(100.0, self.stream.bids)
        self.assertNotIn(101.0, self.stream.asks)
        self.assertEqual(self.stream.bids[99.5], 7.0)
        self.assertEqual(self.stream.asks[100.5], 6.0)
        self.assertEqual(self.stream.last_update_id, 102)

    def test_invalid_update_row_shape_is_rejected_before_mutation(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        event = {
            "U": 101, "u": 102, "pu": 100,
            "b": [["99.5", "7", "extra"]],
            "a": [],
        }
        with self.assertRaisesRegex(ValueError, "malformed level"):
            self.stream._apply_event(event)
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)


    def test_snapshot_large_integer_overflow_is_rejected_atomically(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        before_update_id = self.stream.last_update_id
        before_book_update_at = self.stream.last_book_update_at
        with self.assertRaisesRegex(ValueError, "nonnumeric levels"):
            self.stream._load_snapshot({
                "lastUpdateId": 200,
                "bids": [[10 ** 400, "1"]],
                "asks": [["101", "1"]],
            })
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, before_update_id)
        self.assertEqual(self.stream.last_book_update_at, before_book_update_at)
        self.assertEqual(self.stream.snapshot_count, 1)

    def test_live_large_integer_overflow_is_rejected_and_counted(self):
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        before_update_id = self.stream.last_update_id
        before_book_update_at = self.stream.last_book_update_at
        with self.assertRaisesRegex(ValueError, "nonnumeric levels"):
            self.stream._apply_event({
                "U": 101, "u": 102, "pu": 100,
                "b": [[10 ** 400, "1"]],
                "a": [],
            })
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, before_update_id)
        self.assertEqual(self.stream.last_book_update_at, before_book_update_at)
        self.assertEqual(self.stream.invalid_depth_message_count, 1)


if __name__ == "__main__":
    unittest.main()
