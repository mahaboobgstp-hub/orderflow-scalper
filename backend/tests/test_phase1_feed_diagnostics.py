import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app import main
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
        self.assertEqual(status["invalid_depth_message_count"], 0)
        self.assertIsNone(status["last_event_age_seconds"])
        self.assertIsNone(status["last_book_update_age_seconds"])
        self.assertIsNone(status["last_sync_age_seconds"])
        self.assertTrue(status["stale"])
        self.assertFalse(status["fresh"])
        self.assertFalse(status["healthy"])
        self.assertEqual(status["connection_attempt_count"], 0)
        self.assertEqual(status["successful_connection_count"], 0)
        self.assertEqual(status["reconnect_count"], 0)
        self.assertEqual(status["recovery_count"], 0)

    def test_primary_stale_cutoff_normalizes_invalid_values(self):
        for invalid in (None, "", "invalid", float("nan"), float("inf"), float("-inf"), 0, -1, True, False):
            with self.subTest(value=invalid):
                stream = BinanceOrderBookStream(stale_after_seconds=invalid)
                self.assertEqual(stream.stale_after_seconds, 3.0)

        self.assertEqual(BinanceOrderBookStream(stale_after_seconds=5).stale_after_seconds, 5.0)
        self.assertEqual(BinanceOrderBookStream(stale_after_seconds=0.05).stale_after_seconds, 0.1)

    def test_status_distinguishes_connected_and_synchronized_uptime(self):
        with patch("app.market_data.backend_stream.time.time", return_value=100.0):
            self.stream.connected = True
            self.stream.synchronized = True
            self.stream.connected_at = 90.0
            self.stream.synchronized_since = 95.0
            self.stream.last_event_at = 98.5
            self.stream.last_book_update_at = 98.5
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
            self.stream.last_book_update_at = 96.0
            status = __import__("asyncio").run(self.stream.get_status())
        self.assertTrue(status["synchronized"])
        self.assertTrue(status["stale"])
        self.assertFalse(status["healthy"])
        self.assertEqual(status["last_event_age_seconds"], 4.0)
        self.assertEqual(status["last_book_update_age_seconds"], 4.0)

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

    def test_snapshot_bridge_accepts_event_without_snapshot_pu_match(self):
        with patch("app.market_data.backend_stream.time.time", return_value=50.0):
            self.stream._load_snapshot({
                "lastUpdateId": 100,
                "bids": [["99", "2"]],
                "asks": [["101", "4"]],
            })
            self.stream.successful_connection_count = 1
            event = {"U": 100, "u": 101, "pu": 99, "b": [["100", "1"]], "a": []}
            self.assertTrue(self.stream._event_bridges_snapshot(event))
            self.assertTrue(self.stream._apply_snapshot_bridge(event))
        self.assertTrue(self.stream.synchronized)
        self.assertEqual(self.stream.last_update_id, 101)
        self.assertEqual(self.stream.bids[100.0], 1.0)


    def test_snapshot_bridge_rejects_non_overlapping_event(self):
        self.stream.last_update_id = 100
        event = {"U": 102, "u": 103, "pu": 100, "b": [["100", "1"]], "a": []}
        self.assertFalse(self.stream._event_bridges_snapshot(event))
        self.assertFalse(self.stream._apply_snapshot_bridge(event))
        self.assertFalse(self.stream.synchronized)
        self.assertEqual(self.stream.last_update_id, 100)


    def test_live_events_enforce_pu_after_snapshot_bridge(self):
        self.stream._load_snapshot({
            "lastUpdateId": 100,
            "bids": [["100", "2"]],
            "asks": [["101", "4"]],
        })
        bridge = {"U": 100, "u": 101, "pu": 99, "b": [], "a": []}
        self.assertTrue(self.stream._apply_snapshot_bridge(bridge))
        self.assertTrue(self.stream._apply_event({"U": 102, "u": 103, "pu": 101, "b": [], "a": []}))
        self.assertEqual(self.stream.last_update_id, 103)
        self.assertFalse(self.stream._apply_event({"U": 104, "u": 105, "pu": 102, "b": [], "a": []}))
        self.assertEqual(self.stream.last_update_id, 103)

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

    def test_snapshot_bridge_requires_futures_snapshot_id_overlap(self):
        self.stream.last_update_id = 100
        self.assertTrue(self.stream._event_bridges_snapshot({"U": 100, "u": 100}))
        self.assertTrue(self.stream._event_bridges_snapshot({"U": 100, "u": 101}))
        self.assertFalse(self.stream._event_bridges_snapshot({"U": 101, "u": 102}))
        self.assertFalse(self.stream._event_bridges_snapshot({"U": 98, "u": 99}))
        self.assertFalse(self.stream._event_bridges_snapshot({"U": 102, "u": 103}))

    def test_sequence_gap_is_rejected_by_book_update(self):
        self.stream.last_update_id = 100
        self.assertFalse(self.stream._apply_event({
            "U": 105, "u": 106, "b": [["100", "1"]], "a": []
        }))
        self.assertEqual(self.stream.last_update_id, 100)


    def test_observability_route_exposes_phase_a_feed_schema(self):
        class FakeUnified:
            def get_status(self):
                return {
                    "stale_after_seconds": 3.0,
                    "books": {
                        "bybit:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None}
                    },
                    "exchanges": {
                        "bybit": {"messages_received": 12, "last_message_age_seconds": 0.25}
                    },
                    "trade_streams": {},
                    "errors": {},
                }

        class FakePrimary:
            async def get_status(self):
                return {
                    "symbol": "BTCUSDT", "connected": True, "synchronized": True,
                    "stale": False, "fresh": True, "healthy": True,
                    "stale_after_seconds": 3.0, "last_update_id": 101,
                    "connected_duration_seconds": 40.0, "synchronized_duration_seconds": 35.0,
                    "last_event_age_seconds": 0.25, "last_sync_age_seconds": 5.0,
                    "last_disconnect_at": None, "last_disconnect_reason": None,
                    "connection_attempt_count": 1, "successful_connection_count": 1,
                    "reconnect_count": 0, "recovery_count": 0,
                    "last_reconnect_at": None, "last_recovery_at": None,
                    "last_recovery_age_seconds": None, "messages_received": 12,
                    "snapshot_count": 1, "sequence_gap_count": 0,
                }

        class FakeExchanges:
            async def status(self):
                return {"exchanges": [{
                    "exchange": "bybit", "symbol": "BTCUSDT", "connected": True,
                    "last_message_age_seconds": 0.25, "last_error": None,
                }]}

        state = main.app.state
        names = ("market_stream", "unified_market_data", "exchange_manager")
        originals = {name: getattr(state, name, None) for name in names}
        missing = {name: not hasattr(state, name) for name in names}
        state.market_stream = FakePrimary()
        state.unified_market_data = FakeUnified()
        state.exchange_manager = FakeExchanges()
        try:
            payload = asyncio.run(main.market_data_observability())
        finally:
            for name in names:
                if missing[name]:
                    delattr(state, name)
                else:
                    setattr(state, name, originals[name])

        primary = payload["primary_binance_demo_stream"]
        for field in (
            "stale", "fresh", "healthy", "stale_after_seconds",
            "connected_duration_seconds", "synchronized_duration_seconds",
            "connection_attempt_count", "successful_connection_count",
            "reconnect_count", "recovery_count", "last_disconnect_reason",
            "last_recovery_age_seconds", "messages_received", "snapshot_count",
            "sequence_gap_count", "invalid_depth_message_count",
        ):
            self.assertIn(field, primary)
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload["mode"], "PUBLIC_MARKET_DATA_PAPER_ONLY")
        self.assertEqual(payload["summary"]["synchronized_book_count"], 1)
        self.assertEqual(payload["summary"]["healthy_feed_count"], 1)
        self.assertEqual(payload["summary"]["fresh_message_feed_count"], 1)

    def test_healthy_feed_count_requires_fresh_synchronized_book(self):
        class FakeUnified:
            def get_status(self):
                return {
                    "stale_after_seconds": 3.0,
                    "books": {
                        "bybit:BTCUSDT": {
                            "synchronized": True, "stale": False, "integrity_error": None
                        },
                        "delta:BTCUSDT": {
                            "synchronized": False, "stale": False, "integrity_error": "awaiting snapshot"
                        },
                    },
                    "exchanges": {},
                    "trade_streams": {},
                    "errors": {},
                }

        class FakePrimary:
            async def get_status(self):
                return {"symbol": "BTCUSDT", "connected": False, "synchronized": False, "stale": True}

        class FakeExchanges:
            async def status(self):
                return {"exchanges": [
                    {"exchange": "bybit", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 0.2, "last_error": None},
                    {"exchange": "delta", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 0.2, "last_error": None},
                ]}

        state = main.app.state
        names = ("market_stream", "unified_market_data", "exchange_manager")
        originals = {name: getattr(state, name, None) for name in names}
        missing = {name: not hasattr(state, name) for name in names}
        state.market_stream = FakePrimary()
        state.unified_market_data = FakeUnified()
        state.exchange_manager = FakeExchanges()
        try:
            payload = asyncio.run(main.market_data_observability())
        finally:
            for name in names:
                if missing[name]:
                    delattr(state, name)
                else:
                    setattr(state, name, originals[name])

        self.assertEqual(payload["summary"]["fresh_message_feed_count"], 2)
        self.assertEqual(payload["summary"]["healthy_feed_count"], 1)
        self.assertEqual(payload["summary"]["synchronized_book_count"], 1)

    def test_feed_health_summary_excludes_stale_messages_and_integrity_errors(self):
        result = main._feed_health_counts(
            {"exchanges": [
                {"exchange": "bybit", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 0.2},
                {"exchange": "delta", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 0.2},
                {"exchange": "binance", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 4.0},
                {"exchange": "disabled", "symbol": "BTCUSDT", "enabled": False, "connected": True, "last_message_age_seconds": 0.1},
            ]},
            {"stale_after_seconds": 3.0, "books": {
                "bybit:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None},
                "delta:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": "sequence mismatch"},
                "binance:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None},
                "disabled:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None},
            }},
        )
        self.assertEqual(result["fresh_message_feed_count"], 2)
        self.assertEqual(result["healthy_feed_count"], 1)

    def test_feed_health_summary_rejects_invalid_message_ages(self):
        adapters = [
            {"exchange": "negative", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": -0.1},
            {"exchange": "nan", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": float("nan")},
            {"exchange": "infinite", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": float("inf")},
            {"exchange": "malformed", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": "not-a-number"},
            {"exchange": "boolean_true", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": True},
            {"exchange": "boolean_false", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": False},
            {"exchange": "valid", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 0.2},
        ]
        result = main._feed_health_counts(
            {"exchanges": adapters},
            {"stale_after_seconds": 3.0, "books": {
                "valid:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None},
            }},
        )
        self.assertEqual(result["fresh_message_feed_count"], 1)
        self.assertEqual(result["healthy_feed_count"], 1)

    def test_invalid_freshness_threshold_falls_back_safely(self):
        adapters = [
            {"exchange": "valid", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 2.5},
            {"exchange": "too_old", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 3.1},
        ]
        books = {
            "valid:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None},
        }
        for threshold in (float("nan"), float("inf"), -1.0, "invalid", True, False):
            with self.subTest(threshold=threshold):
                result = main._feed_health_counts(
                    {"exchanges": adapters},
                    {"stale_after_seconds": threshold, "books": books},
                )
                self.assertEqual(result["fresh_message_feed_count"], 1)
                self.assertEqual(result["healthy_feed_count"], 1)

    def test_depth_frame_decoder_accepts_valid_update_ids(self):
        event = self.stream._decode_depth_message(
            '{"U":100,"u":101,"pu":99,"b":[],"a":[]}'
        )
        self.assertEqual(event["U"], 100)
        self.assertEqual(event["u"], 101)

    def test_depth_frame_decoder_rejects_malformed_shapes_and_ranges(self):
        invalid_frames = (
            "{",
            "[]",
            '{"U":100}',
            '{"U":102,"u":101}',
            '{"U":true,"u":101}',
            '{"U":100.5,"u":101}',
            '{"U":100,"u":101,"pu":100.5}',
            '{"U":100,"u":101,"pu":true}',
            '{"U":100,"u":101,"pu":-1}',
        )
        for frame in invalid_frames:
            with self.subTest(frame=frame):
                with self.assertRaises(ValueError):
                    self.stream._decode_depth_message(frame)

    def test_collector_signals_termination_after_malformed_frame(self):
        class FakeWebSocket:
            def __init__(self, messages):
                self.messages = messages

            def __aiter__(self):
                async def iterate():
                    for message in self.messages:
                        yield message
                return iterate()

        async def run_collector():
            queue = asyncio.Queue()
            await self.stream._collect_depth_events(
                FakeWebSocket(['{"U":100,"u":101,"b":[],"a":[]}', "{broken-json"]),
                queue,
            )
            return await queue.get(), await queue.get()

        first, sentinel = asyncio.run(run_collector())
        self.assertEqual(first["U"], 100)
        self.assertIsNone(sentinel)
        self.assertEqual(self.stream.messages_received, 2)
        self.assertEqual(self.stream.last_error, "Malformed Binance depth JSON frame")
        self.assertEqual(self.stream.invalid_depth_message_count, 1)

    def test_collector_signals_normal_websocket_end(self):
        class FakeWebSocket:
            def __init__(self, messages):
                self.messages = messages

            def __aiter__(self):
                async def iterate():
                    for message in self.messages:
                        yield message
                return iterate()

        async def run_collector():
            queue = asyncio.Queue()
            await self.stream._collect_depth_events(
                FakeWebSocket(['{"U":100,"u":101,"b":[],"a":[]}']),
                queue,
            )
            return await queue.get(), await queue.get()

        event, sentinel = asyncio.run(run_collector())
        self.assertEqual(event["u"], 101)
        self.assertIsNone(sentinel)
        self.assertIsNone(self.stream.last_error)

    def test_snapshot_loader_rejects_invalid_levels_without_mutating_book(self):
        self.stream.bids = {100.0: 2.0}
        self.stream.asks = {101.0: 3.0}
        self.stream.last_update_id = 42
        invalid_snapshots = (
            {"lastUpdateId": 43, "bids": [["nan", "1"]], "asks": [["101", "1"]]},
            {"lastUpdateId": 43, "bids": [["100", "1"]], "asks": [["101", "inf"]]},
            {"lastUpdateId": 43, "bids": [["-100", "1"]], "asks": [["101", "1"]]},
            {"lastUpdateId": 43, "bids": [["100", "-1"]], "asks": [["101", "1"]]},
            {"lastUpdateId": 43, "bids": [["100"]], "asks": [["101", "1"]]},
            {"lastUpdateId": 43, "bids": [["100", "1"]], "asks": []},
            {"lastUpdateId": 43.0, "bids": [["100", "1"]], "asks": [["101", "1"]]},
            {"lastUpdateId": 43, "bids": [[True, "1"]], "asks": [["101", "1"]]},
            {"lastUpdateId": 43, "bids": [["100", True]], "asks": [["101", "1"]]},
            {"lastUpdateId": 43, "bids": [["100", "1", "extra"]], "asks": [["101", "1"]]},
        )
        for snapshot in invalid_snapshots:
            with self.subTest(snapshot=snapshot):
                with self.assertRaises(ValueError):
                    self.stream._load_snapshot(snapshot)
                self.assertEqual(self.stream.bids, {100.0: 2.0})
                self.assertEqual(self.stream.asks, {101.0: 3.0})
                self.assertEqual(self.stream.last_update_id, 42)

    def test_snapshot_loader_discards_zero_quantity_levels(self):
        self.stream._load_snapshot({
            "lastUpdateId": 42,
            "bids": [["100", "2"], ["99", "0"]],
            "asks": [["101", "3"], ["102", "0"]],
        })
        self.assertEqual(self.stream.bids, {100.0: 2.0})
        self.assertEqual(self.stream.asks, {101.0: 3.0})
        self.assertFalse(self.stream.synchronized)

    def test_database_status_route_is_read_only(self):
        async def invoke():
            with patch.object(main.database, "check_connection", new=AsyncMock(return_value=True)) as check, \
                 patch.object(main.database, "status", new=AsyncMock(return_value={"provider": "supabase", "connected": True})) as status, \
                 patch.object(main.database, "write_heartbeat", new=AsyncMock(return_value=True)) as heartbeat:
                payload = await main.database_status()
                check.assert_awaited_once()
                status.assert_awaited_once_with(refresh=False)
                heartbeat.assert_not_awaited()
                return payload

        route = next(route for route in main.app.routes if getattr(route, "path", None) == "/api/database/status")
        self.assertEqual(route.methods, {"GET"})
        payload = asyncio.run(invoke())
        self.assertEqual(payload["diagnostic_mode"], "read_only")
        self.assertIsNone(payload["heartbeat_write_verified"])
        self.assertTrue(payload["connected"])


if __name__ == "__main__":
    unittest.main()
