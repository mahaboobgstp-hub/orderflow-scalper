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
        self.assertFalse(self.stream._event_bridges_snapshot(self.event(98, 100)))

    def test_bridge_event_with_next_update_id_is_accepted(self):
        self.assertTrue(self.stream._event_bridges_snapshot(self.event(100, 101)))

    def test_bridge_event_exact_next_id_is_accepted(self):
        self.assertTrue(self.stream._event_bridges_snapshot(self.event(101, 101)))

    def test_event_starting_after_required_next_id_is_rejected(self):
        self.assertFalse(self.stream._event_bridges_snapshot(self.event(102, 103)))

    def test_event_final_id_before_snapshot_is_rejected(self):
        self.assertFalse(self.stream._event_bridges_snapshot(self.event(95, 99)))

    def test_snapshot_missing_update_id_rejects_bridge(self):
        self.stream.last_update_id = None
        self.assertFalse(self.stream._event_bridges_snapshot(self.event(1, 2)))

    def test_apply_first_bridging_event_updates_book_and_sequence(self):
        e = self.event(100, 101, bids=[["100.0", "0"], ["99.5", "7"]], asks=[["101.0", "6"]])
        self.assertTrue(self.stream._event_bridges_snapshot(e))
        self.assertTrue(self.stream._apply_event(e))
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
        with self.assertRaises((ValueError, TypeError)):
            self.stream._apply_event(e)

    def test_stop_marks_stream_unsynchronized(self):
        self.assertFalse(self.stream.synchronized)
        self.assertIsNotNone(self.stream.last_update_id)


if __name__ == "__main__":
    unittest.main()
