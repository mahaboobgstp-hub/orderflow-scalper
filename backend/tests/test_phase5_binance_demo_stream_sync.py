import asyncio
import unittest
from unittest.mock import patch

from app.market_data.backend_stream import BinanceOrderBookStream


def stream_with_snapshot(update_id=100):
    stream = BinanceOrderBookStream(symbol="BTCUSDT")
    stream._load_snapshot(
        {
            "lastUpdateId": update_id,
            "bids": [["100.0", "1.0"]],
            "asks": [["101.0", "1.0"]],
        }
    )
    return stream


def depth_event(U, u, pu=None, bids=None, asks=None):
    event = {
        "U": U,
        "u": u,
        "b": bids or [],
        "a": asks or [],
    }
    if pu is not None:
        event["pu"] = pu
    return event


class BinanceDemoDepthSyncTests(unittest.TestCase):
    def test_snapshot_bridge_requires_covering_next_update_id(self):
        stream = stream_with_snapshot(100)

        self.assertTrue(stream._event_bridges_snapshot(depth_event(100, 101)))
        self.assertTrue(stream._event_bridges_snapshot(depth_event(101, 101)))
        self.assertTrue(stream._event_bridges_snapshot(depth_event(99, 102)))

        # Events ending at the snapshot ID are already covered.
        self.assertFalse(stream._event_bridges_snapshot(depth_event(99, 100)))
        self.assertFalse(stream._event_bridges_snapshot(depth_event(100, 100)))

        # A later event that starts after the required update is a gap.
        self.assertFalse(stream._event_bridges_snapshot(depth_event(102, 103)))

    def test_snapshot_bridge_rejects_malformed_or_reversed_sequences(self):
        stream = stream_with_snapshot(100)

        self.assertFalse(stream._event_bridges_snapshot({"u": 101}))
        self.assertFalse(stream._event_bridges_snapshot({"U": "bad", "u": 101}))
        self.assertFalse(stream._event_bridges_snapshot(depth_event(102, 101)))
        self.assertFalse(stream._event_bridges_snapshot(depth_event(101, 100)))

    def test_initial_bridge_ignores_stream_previous_id_and_applies_event(self):
        stream = stream_with_snapshot(100)
        event = depth_event(
            100,
            101,
            pu=98,  # Stream predecessor is not the REST snapshot update ID.
            bids=[["100.0", "2.5"]],
            asks=[["101.0", "0"]],
        )

        self.assertTrue(stream._event_bridges_snapshot(event))
        self.assertTrue(stream._apply_event(event, initial_snapshot_bridge=True))
        self.assertEqual(stream.last_update_id, 101)
        self.assertEqual(stream.bids[100.0], 2.5)
        self.assertNotIn(101.0, stream.asks)

    def test_initial_bridge_does_not_apply_nonbridging_events(self):
        stream = stream_with_snapshot(100)
        nonbridging_events = (
            depth_event(100, 100),
            depth_event(102, 103),
            depth_event(101, 100),
        )

        for event in nonbridging_events:
            with self.subTest(event=event):
                before_bids = dict(stream.bids)
                before_asks = dict(stream.asks)
                self.assertFalse(
                    stream._apply_event(event, initial_snapshot_bridge=True)
                )
                self.assertEqual(stream.last_update_id, 100)
                self.assertEqual(stream.bids, before_bids)
                self.assertEqual(stream.asks, before_asks)

    def test_subsequent_event_requires_matching_pu(self):
        stream = stream_with_snapshot(100)
        bridge = depth_event(100, 101, pu=98, bids=[["100", "2"]])
        self.assertTrue(stream._apply_event(bridge, initial_snapshot_bridge=True))

        contiguous = depth_event(102, 103, pu=101, bids=[["100", "3"]])
        self.assertTrue(stream._apply_event(contiguous))
        self.assertEqual(stream.last_update_id, 103)
        self.assertEqual(stream.bids[100.0], 3.0)

        gap = depth_event(104, 105, pu=102, bids=[["100", "9"]])
        self.assertFalse(stream._apply_event(gap))
        self.assertEqual(stream.last_update_id, 103)
        self.assertEqual(stream.bids[100.0], 3.0)

    def test_subsequent_event_without_pu_uses_update_range_gap_fallback(self):
        stream = stream_with_snapshot(100)
        bridge = depth_event(101, 101, bids=[["100", "2"]])
        self.assertTrue(stream._apply_event(bridge, initial_snapshot_bridge=True))

        contiguous = depth_event(102, 102, bids=[["100", "3"]])
        self.assertTrue(stream._apply_event(contiguous))
        self.assertEqual(stream.last_update_id, 102)

        gap = depth_event(104, 104, bids=[["100", "8"]])
        self.assertFalse(stream._apply_event(gap))
        self.assertEqual(stream.last_update_id, 102)

    def test_duplicate_or_old_events_are_ignored_without_mutation(self):
        stream = stream_with_snapshot(100)
        bridge = depth_event(100, 101, bids=[["100", "2"]])
        self.assertTrue(stream._apply_event(bridge, initial_snapshot_bridge=True))

        duplicate = depth_event(100, 101, bids=[["100", "99"]])
        old = depth_event(90, 99, bids=[["100", "99"]])

        self.assertTrue(stream._apply_event(duplicate))
        self.assertTrue(stream._apply_event(old))
        self.assertEqual(stream.last_update_id, 101)
        self.assertEqual(stream.bids[100.0], 2.0)

    def test_valid_update_advances_freshness_but_duplicate_does_not(self):
        stream = stream_with_snapshot(100)
        bridge = depth_event(100, 101, bids=[["100.0", "2.0"]])
        stream.connected = True
        with patch("app.market_data.backend_stream.time.monotonic", return_value=100.0):
            self.assertTrue(stream._apply_event(bridge, initial_snapshot_bridge=True))
        stream.synchronized = True
        self.assertEqual(stream._last_event_received_at, 100.0)

        contiguous = depth_event(102, 103, pu=101, bids=[["100.0", "3.0"]])
        with patch("app.market_data.backend_stream.time.monotonic", return_value=101.0):
            self.assertTrue(stream._apply_event(contiguous))
        self.assertEqual(stream._last_event_received_at, 101.0)

        duplicate = depth_event(102, 103, pu=101, bids=[["100.0", "99.0"]])
        with patch("app.market_data.backend_stream.time.monotonic", return_value=105.0):
            self.assertTrue(stream._apply_event(duplicate))
            self.assertEqual(stream._last_event_received_at, 101.0)
            stale_book = asyncio.run(stream.get_order_book())

        self.assertIsNone(stale_book)
        self.assertEqual(stream.last_update_id, 103)
        self.assertEqual(stream.bids[100.0], 3.0)


if __name__ == "__main__":
    unittest.main()
