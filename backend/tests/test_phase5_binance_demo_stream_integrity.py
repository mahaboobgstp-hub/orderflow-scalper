import time
import unittest
from unittest.mock import patch

from app.market_data.backend_stream import BinanceOrderBookStream


def valid_snapshot():
    return {
        "lastUpdateId": 100,
        "bids": [["100.0", "2.0"], ["99.9", "1.0"]],
        "asks": [["100.1", "2.0"], ["100.2", "1.0"]],
    }


def depth_event(U, u, pu, bids=None, asks=None):
    return {"U": U, "u": u, "pu": pu, "b": bids or [], "a": asks or []}


class BinanceDemoBookIntegrityTests(unittest.TestCase):
    def ready_stream(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        stream._load_snapshot(valid_snapshot())
        stream.connected = True
        stream.synchronized = True
        stream._last_event_received_at = time.monotonic()
        return stream

    def test_accessor_rejects_crossed_and_locked_books(self):
        stream = self.ready_stream()
        stream.bids = {100.2: 2.0}
        stream.asks = {100.1: 1.0}
        self.assertIsNone(__import__("asyncio").run(stream.get_order_book()))

        stream.bids = {100.1: 2.0}
        stream.asks = {100.1: 1.0}
        self.assertIsNone(__import__("asyncio").run(stream.get_order_book()))

    def test_accessor_rejects_nonfinite_and_nonpositive_levels(self):
        for bids, asks in (
            ({float("nan"): 1.0}, {101.0: 1.0}),
            ({100.0: float("inf")}, {101.0: 1.0}),
            ({100.0: -1.0}, {101.0: 1.0}),
            ({100.0: 1.0}, {float("inf"): 1.0}),
            ({100.0: 1.0}, {101.0: 0.0}),
        ):
            with self.subTest(bids=bids, asks=asks):
                stream = self.ready_stream()
                stream.bids, stream.asks = bids, asks
                self.assertIsNone(__import__("asyncio").run(stream.get_order_book()))

    def test_snapshot_rejects_nonfinite_levels_and_crossed_books(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        bad_snapshots = (
            {**valid_snapshot(), "bids": [["nan", "2.0"]]},
            {**valid_snapshot(), "asks": [["101.0", "inf"]]},
            {**valid_snapshot(), "bids": [["101.0", "2.0"]]},
        )
        for snapshot in bad_snapshots:
            with self.subTest(snapshot=snapshot):
                with self.assertRaises(ValueError):
                    stream._load_snapshot(snapshot)

    def test_snapshot_update_id_rejects_float_bool_negative_and_malformed(self):
        stream = self.ready_stream()
        before_bids, before_asks, before_id = dict(stream.bids), dict(stream.asks), stream.last_update_id
        invalid_ids = (100.5, 100.0, True, False, -1, float("nan"), float("inf"), "100.5", "bad", None)
        for update_id in invalid_ids:
            snapshot = {**valid_snapshot(), "lastUpdateId": update_id}
            with self.subTest(update_id=update_id):
                with self.assertRaises(ValueError):
                    stream._load_snapshot(snapshot)
                self.assertEqual(stream.bids, before_bids)
                self.assertEqual(stream.asks, before_asks)
                self.assertEqual(stream.last_update_id, before_id)

    def test_snapshot_and_event_levels_reject_boolean_values(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        bad_snapshots = (
            {**valid_snapshot(), "bids": [[True, "2.0"]]},
            {**valid_snapshot(), "asks": [["101.0", True]]},
        )
        for snapshot in bad_snapshots:
            with self.subTest(snapshot=snapshot):
                with self.assertRaises(ValueError):
                    stream._load_snapshot(snapshot)

        stream = self.ready_stream()
        before_bids, before_asks, before_id = dict(stream.bids), dict(stream.asks), stream.last_update_id
        invalid_events = (
            depth_event(101, 102, 100, bids=[[True, 1.0]]),
            depth_event(101, 102, 100, bids=[[100.0, True]]),
            depth_event(101, 102, 100, asks=[[101.0, True]]),
        )
        for event in invalid_events:
            with self.subTest(event=event):
                self.assertFalse(stream._apply_event(event))
                self.assertEqual(stream.bids, before_bids)
                self.assertEqual(stream.asks, before_asks)
                self.assertEqual(stream.last_update_id, before_id)

    def test_constructor_rejects_boolean_max_book_age(self):
        for value in (True, False):
            with self.subTest(max_book_age_seconds=value):
                with self.assertRaisesRegex(ValueError, "finite"):
                    BinanceOrderBookStream(max_book_age_seconds=value)

    def test_buffered_event_preserves_receive_time_for_freshness(self):
        stream = self.ready_stream()
        received_at = time.monotonic() - stream.max_book_age_seconds - 1.0
        event = depth_event(101, 102, 100, bids=[["100.0", "3.0"]])
        event["_received_monotonic"] = received_at

        self.assertTrue(stream._apply_event(event))
        self.assertEqual(stream._last_event_received_at, received_at)
        self.assertIsNone(__import__("asyncio").run(stream.get_order_book()))

    def test_receive_timestamp_is_stamped_on_event_capture(self):
        stream = self.ready_stream()
        event = {"U": 101, "u": 101}
        with patch("app.market_data.backend_stream.time.monotonic", return_value=123.456):
            stamped = stream._stamp_event_received(event)
        self.assertIs(stamped, event)
        self.assertEqual(stamped["_received_monotonic"], 123.456)

    def test_snapshot_integer_string_update_id_is_supported(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        stream._load_snapshot({**valid_snapshot(), "lastUpdateId": "100"})
        self.assertEqual(stream.last_update_id, 100)

    def test_invalid_event_rejected_without_partial_mutation(self):
        stream = self.ready_stream()
        before_bids, before_asks, before_id = dict(stream.bids), dict(stream.asks), stream.last_update_id
        event = depth_event(
            101, 102, 100,
            bids=[["100.0", "3.0"]],
            asks=[["nan", "1.0"]],
        )
        self.assertFalse(stream._apply_event(event))
        self.assertEqual(stream.bids, before_bids)
        self.assertEqual(stream.asks, before_asks)
        self.assertEqual(stream.last_update_id, before_id)

    def test_rejects_fractional_and_boolean_sequence_ids(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        stream._load_snapshot(valid_snapshot())
        bad_initial_events = (
            depth_event(100.5, 101.5, 100),
            depth_event(True, 101, 100),
            depth_event(100, True, 100),
        )
        for event in bad_initial_events:
            with self.subTest(event=event):
                self.assertFalse(stream._event_bridges_snapshot(event))

        stream = self.ready_stream()
        before_bids, before_asks, before_id = dict(stream.bids), dict(stream.asks), stream.last_update_id
        bad_following_events = (
            depth_event(101, 102, 100.5),
            depth_event(101, 102, True),
            depth_event(101.0, 102, 100),
        )
        for event in bad_following_events:
            with self.subTest(event=event):
                self.assertFalse(stream._apply_event(event))
                self.assertEqual(stream.bids, before_bids)
                self.assertEqual(stream.asks, before_asks)
                self.assertEqual(stream.last_update_id, before_id)

    def test_integer_string_sequence_ids_are_supported_without_truncation(self):
        stream = BinanceOrderBookStream("BTCUSDT")
        stream._load_snapshot(valid_snapshot())
        bridge = depth_event("101", "101", "999", bids=[["100.0", "3.0"]])
        self.assertTrue(stream._event_bridges_snapshot(bridge))
        self.assertTrue(stream._apply_event(bridge, initial_snapshot_bridge=True))
        self.assertEqual(stream.last_update_id, 101)
        self.assertEqual(stream.bids[100.0], 3.0)

    def test_valid_deletion_and_update_keep_book_valid(self):
        stream = self.ready_stream()
        event = depth_event(101, 102, 100, bids=[["99.9", "0"], ["100.0", "3.0"]])
        self.assertTrue(stream._apply_event(event))
        self.assertEqual(stream.bids[100.0], 3.0)
        self.assertNotIn(99.9, stream.bids)
        self.assertTrue(stream._book_integrity_valid(stream.bids, stream.asks))


if __name__ == "__main__":
    unittest.main()
