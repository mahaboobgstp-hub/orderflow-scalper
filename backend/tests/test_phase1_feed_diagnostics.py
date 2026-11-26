import unittest

from app.market_data.backend_stream import BinanceOrderBookStream


class Phase1FeedDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.stream = BinanceOrderBookStream(symbol="BTCUSDT")

    def test_status_contains_feed_health_metrics(self):
        status = __import__("asyncio").run(self.stream.get_status())
        self.assertFalse(status["connected"])
        self.assertFalse(status["synchronized"])
        self.assertEqual(status["messages_received"], 0)
        self.assertEqual(status["snapshot_count"], 0)
        self.assertEqual(status["sequence_gap_count"], 0)
        self.assertIsNone(status["last_event_age_seconds"])
        self.assertIsNone(status["last_sync_age_seconds"])

    def test_snapshot_load_is_counted_and_not_assumed_synchronized(self):
        self.stream._load_snapshot({
            "lastUpdateId": 100,
            "bids": [["100.0", "2"]],
            "asks": [["101.0", "3"]],
        })
        self.assertEqual(self.stream.snapshot_count, 1)
        self.assertEqual(self.stream.last_update_id, 100)
        self.assertFalse(self.stream.synchronized)

    def test_snapshot_bridge_requires_snapshot_plus_one_in_range(self):
        self.stream.last_update_id = 100
        self.assertTrue(self.stream._event_bridges_snapshot({"U": 100, "u": 101}))
        self.assertTrue(self.stream._event_bridges_snapshot({"U": 101, "u": 102}))
        self.assertFalse(self.stream._event_bridges_snapshot({"U": 98, "u": 100}))
        self.assertFalse(self.stream._event_bridges_snapshot({"U": 102, "u": 103}))

    def test_sequence_gap_is_rejected_by_book_update(self):
        self.stream.last_update_id = 100
        self.assertFalse(self.stream._apply_event({
            "U": 105, "u": 106, "b": [["100", "1"]], "a": []
        }))
        self.assertEqual(self.stream.last_update_id, 100)


if __name__ == "__main__":
    unittest.main()
