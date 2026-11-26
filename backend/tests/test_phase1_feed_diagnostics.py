import unittest
from unittest.mock import patch

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
        self.assertTrue(status["stale"])
        self.assertFalse(status["fresh"])
        self.assertFalse(status["healthy"])
        self.assertEqual(status["connection_attempt_count"], 0)
        self.assertEqual(status["successful_connection_count"], 0)
        self.assertEqual(status["reconnect_count"], 0)
        self.assertEqual(status["recovery_count"], 0)

    def test_status_distinguishes_connected_and_synchronized_uptime(self):
        with patch("app.market_data.backend_stream.time.time", return_value=100.0):
            self.stream.connected = True
            self.stream.synchronized = True
            self.stream.connected_at = 90.0
            self.stream.synchronized_since = 95.0
            self.stream.last_event_at = 98.5
            status = __import__("asyncio").run(self.stream.get_status())
        self.assertFalse(status["stale"])
        self.assertTrue(status["fresh"])
        self.assertTrue(status["healthy"])
        self.assertEqual(status["connected_duration_seconds"], 10.0)
        self.assertEqual(status["synchronized_duration_seconds"], 5.0)
        self.assertEqual(status["last_event_age_seconds"], 1.5)

    def test_stale_feed_is_unhealthy_even_if_book_flag_is_synchronized(self):
        with patch("app.market_data.backend_stream.time.time", return_value=100.0):
            self.stream.connected = True
            self.stream.synchronized = True
            self.stream.connected_at = 90.0
            self.stream.synchronized_since = 95.0
            self.stream.last_event_at = 96.0
            status = __import__("asyncio").run(self.stream.get_status())
        self.assertTrue(status["synchronized"])
        self.assertTrue(status["stale"])
        self.assertFalse(status["healthy"])
        self.assertEqual(status["last_event_age_seconds"], 4.0)

    def test_reconnect_and_snapshot_recovery_metrics(self):
        self.stream._record_connection_attempt()
        self.stream._record_connection_success(now=10.0)
        self.stream._record_synchronized(now=11.0)
        self.stream._record_connection_attempt()
        self.stream._record_connection_success(now=20.0)
        self.stream._record_synchronized(now=21.0)
        status = __import__("asyncio").run(self.stream.get_status())
        self.assertEqual(status["connection_attempt_count"], 2)
        self.assertEqual(status["successful_connection_count"], 2)
        self.assertEqual(status["reconnect_count"], 1)
        self.assertEqual(status["recovery_count"], 1)
        self.assertEqual(status["last_reconnect_at"], 20.0)
        self.assertEqual(status["last_recovery_at"], 21.0)

    def test_snapshot_bridge_rejects_failed_continuity_application(self):
        self.stream.last_update_id = 100
        event = {"U": 100, "u": 101, "pu": 99, "b": [["100", "1"]], "a": []}
        self.assertTrue(self.stream._event_bridges_snapshot(event))
        self.assertFalse(self.stream._apply_snapshot_bridge(event))
        self.assertFalse(self.stream.synchronized)
        self.assertEqual(self.stream.last_update_id, 100)

    def test_snapshot_bridge_marks_sync_only_after_event_applies(self):
        with patch("app.market_data.backend_stream.time.time", return_value=50.0):
            self.stream.last_update_id = 100
            self.stream.successful_connection_count = 1
            event = {"U": 100, "u": 101, "pu": 100, "b": [["100", "2"]], "a": [["101", "1"]]}
            self.assertTrue(self.stream._apply_snapshot_bridge(event))
            status = __import__("asyncio").run(self.stream.get_status())
        self.assertTrue(status["synchronized"])
        self.assertEqual(status["last_update_id"], 101)
        self.assertEqual(status["synchronized_duration_seconds"], 0.0)
        self.assertEqual(status["recovery_count"], 0)

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
