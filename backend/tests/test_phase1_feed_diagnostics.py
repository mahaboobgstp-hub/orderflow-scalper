import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app import main
from app.market_data.backend_stream import BinanceOrderBookStream, SNAPSHOT_BUFFER_MAX_EVENTS


class Phase1FeedDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.stream = BinanceOrderBookStream(symbol="BTCUSDT")

    def _prime_synchronized_book(self):
        with patch("app.market_data.backend_stream.time.time", return_value=100.0):
            self.stream._record_connection_success(now=100.0)
            self.stream._load_snapshot({
                "lastUpdateId": 100,
                "bids": [["100", "2"]],
                "asks": [["101", "3"]],
            })
            self.assertTrue(self.stream._apply_snapshot_bridge({
                "U": 100, "u": 101, "pu": 99,
                "b": [["99.5", "1"]], "a": [],
            }))
        self.assertTrue(self.stream.synchronized)

    def test_status_contains_feed_health_metrics(self):
        status = __import__("asyncio").run(self.stream.get_status())
        self.assertFalse(status["connected"])
        self.assertFalse(status["synchronized"])
        self.assertEqual(status["messages_received"], 0)
        self.assertEqual(status["snapshot_count"], 0)
        self.assertEqual(status["sequence_gap_count"], 0)
        self.assertEqual(status["invalid_depth_message_count"], 0)
        self.assertEqual(status["snapshot_buffer_overflow_count"], 0)
        self.assertEqual(status["snapshot_limit"], 1000)
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
        bridge = {"U": 100, "u": 101, "pu": 99, "b": [["99.5", "1"]], "a": []}
        self.assertTrue(self.stream._apply_snapshot_bridge(bridge))
        self.assertTrue(self.stream._apply_event({"U": 102, "u": 103, "pu": 101, "b": [["99.5", "2"]], "a": []}))
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

    def test_live_depth_event_requires_previous_update_id(self):
        self.stream._load_snapshot({
            "lastUpdateId": 100,
            "bids": [["100", "2"]],
            "asks": [["101", "3"]],
        })
        self.stream.synchronized = True
        before_bids = dict(self.stream.bids)
        before_asks = dict(self.stream.asks)
        self.assertFalse(self.stream._apply_event({
            "U": 101, "u": 102, "b": [["99.5", "1"]], "a": []
        }))
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, 100)

    def test_sequence_gap_is_rejected_by_book_update(self):
        self.stream.last_update_id = 100
        self.stream.synchronized = True
        self.assertFalse(self.stream._apply_event({
            "U": 105, "u": 106, "pu": 104, "b": [["100", "1"]], "a": []
        }))
        self.assertEqual(self.stream.last_update_id, 100)


    def test_observability_route_exposes_phase_a_feed_schema(self):
        class FakeUnified:
            def get_status(self):
                return {
                    "stale_after_seconds": 3.0,
                    "books": {
                        "bybit:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None, "age_seconds": 0.25, "best_bid": 100.0, "best_ask": 101.0},
                        "bybit:ETHUSDT": {"synchronized": True, "stale": False, "integrity_error": None}
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
                    "symbol": "BTCUSDT", "snapshot_limit": 1000, "connected": True, "synchronized": True,
                    "stale": False, "fresh": True, "healthy": True,
                    "stale_after_seconds": 3.0, "last_update_id": 101,
                    "connected_duration_seconds": 40.0, "synchronized_duration_seconds": 35.0,
                    "last_event_age_seconds": 0.25, "last_book_update_age_seconds": 0.1, "last_sync_age_seconds": 5.0,
                    "last_disconnect_at": None, "last_disconnect_reason": None,
                    "connection_attempt_count": 1, "successful_connection_count": 1,
                    "reconnect_count": 0, "recovery_count": 0,
                    "last_reconnect_at": None, "last_recovery_at": None,
                    "last_recovery_age_seconds": None, "messages_received": 12,
                    "snapshot_count": 1, "sequence_gap_count": 0,
                    "invalid_depth_message_count": 0,
                    "snapshot_buffer_overflow_count": 0,
                }

        class FakeExchanges:
            async def status(self):
                return {"exchanges": [
                    {"exchange": "bybit", "symbol": "BTCUSDT", "connected": True,
                     "last_message_age_seconds": 0.25, "last_error": None},
                    {"exchange": "truthy", "symbol": "BTCUSDT", "connected": "true",
                     "last_message_age_seconds": 0.1, "last_error": None},
                    None,
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

        primary = payload["primary_binance_demo_stream"]
        for field in (
            "stale", "fresh", "healthy", "stale_after_seconds",
            "connected_duration_seconds", "synchronized_duration_seconds",
            "connection_attempt_count", "successful_connection_count",
            "reconnect_count", "recovery_count", "last_disconnect_reason",
            "last_recovery_age_seconds", "last_book_update_age_seconds", "messages_received", "snapshot_count",
            "sequence_gap_count", "invalid_depth_message_count",
            "snapshot_buffer_overflow_count",
            "snapshot_limit",
        ):
            self.assertIn(field, primary)
        self.assertFalse(payload["live_execution_enabled"])
        self.assertEqual(payload["mode"], "PUBLIC_MARKET_DATA_PAPER_ONLY")
        self.assertEqual(payload["summary"]["unified_book_count"], 2)
        self.assertEqual(payload["summary"]["synchronized_book_count"], 1)
        self.assertEqual(payload["summary"]["healthy_feed_count"], 1)
        self.assertEqual(payload["summary"]["fresh_message_feed_count"], 1)
        self.assertEqual(payload["summary"]["exchange_adapter_count"], 3)
        self.assertEqual(payload["summary"]["feed_errors"], 2)

    def test_healthy_feed_count_requires_fresh_synchronized_book(self):
        class FakeUnified:
            def get_status(self):
                return {
                    "stale_after_seconds": 3.0,
                    "books": {
                        "bybit:BTCUSDT": {
                            "synchronized": True, "stale": False, "integrity_error": None,
                            "age_seconds": 0.2, "best_bid": 100.0, "best_ask": 101.0
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
                "bybit:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None, "age_seconds": 0.2, "best_bid": 100.0, "best_ask": 101.0},
                "delta:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": "sequence mismatch", "age_seconds": 0.2},
                "binance:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None, "age_seconds": 0.2, "best_bid": 100.0, "best_ask": 101.0},
                "disabled:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None, "age_seconds": 0.1, "best_bid": 100.0, "best_ask": 101.0},
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
                "valid:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None, "age_seconds": 0.2, "best_bid": 100.0, "best_ask": 101.0},
            }},
        )
        self.assertEqual(result["fresh_message_feed_count"], 1)
        self.assertEqual(result["healthy_feed_count"], 1)

    def test_feed_health_summary_rejects_missing_and_invalid_book_ages(self):
        adapter = {"exchange": "bybit", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 0.2}
        invalid_ages = (None, True, False, -0.01, float("nan"), float("inf"), 3.01, 10**1000, "invalid")
        for age in invalid_ages:
            with self.subTest(age=age):
                book = {"synchronized": True, "stale": False, "integrity_error": None, "best_bid": 100.0, "best_ask": 101.0}
                if age is not None:
                    book["age_seconds"] = age
                result = main._feed_health_counts(
                    {"exchanges": [adapter]},
                    {"stale_after_seconds": 3.0, "books": {"bybit:BTCUSDT": book}},
                )
                self.assertEqual(result["fresh_message_feed_count"], 1)
                self.assertEqual(result["healthy_feed_count"], 0)

    def test_summary_stale_cutoff_uses_engine_minimum_clamp(self):
        result = main._feed_health_counts(
            {"exchanges": [{
                "exchange": "bybit", "symbol": "BTCUSDT", "connected": True,
                "last_message_age_seconds": 0.08,
            }]},
            {"stale_after_seconds": 0.05, "books": {
                "bybit:BTCUSDT": {
                    "synchronized": True, "stale": False, "integrity_error": None,
                    "age_seconds": 0.09, "best_bid": 100.0, "best_ask": 101.0,
                },
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
            "valid:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None, "age_seconds": 0.2, "best_bid": 100.0, "best_ask": 101.0},
        }
        for threshold in (float("nan"), float("inf"), -1.0, 10**1000, "invalid", True, False):
            with self.subTest(threshold=threshold):
                result = main._feed_health_counts(
                    {"exchanges": adapters},
                    {"stale_after_seconds": threshold, "books": books},
                )
                self.assertEqual(result["fresh_message_feed_count"], 1)
                self.assertEqual(result["healthy_feed_count"], 1)

    def test_depth_frame_decoder_accepts_valid_update_ids(self):
        event = self.stream._decode_depth_message(
            '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[],"a":[]}'
        )
        self.assertEqual(event["U"], 100)
        self.assertEqual(event["u"], 101)

    def test_depth_frame_decoder_rejects_malformed_shapes_and_ranges(self):
        invalid_frames = (
            "{",
            "[]",
            '{"e":"depthUpdate","s":"BTCUSDT","U":100}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"b":[],"a":[]}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":102,"u":101,"pu":99}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":true,"u":101,"pu":99}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":100.5,"u":101,"pu":99}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":100.5}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":true}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":-1}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":"100","u":101,"pu":99}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":"101","pu":99}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":"99"}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":"+100","u":101,"pu":99}',
            '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":"+99"}',
            '{"s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[],"a":[]}',
            '{"e":"aggTrade","s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[],"a":[]}',
            '{"e":"depthUpdate","s":"ETHUSDT","U":100,"u":101,"pu":99,"b":[],"a":[]}',
            '{"e":"depthUpdate","U":100,"u":101,"pu":99,"b":[],"a":[]}',
        )
        for frame in invalid_frames:
            with self.subTest(frame=frame):
                with self.assertRaises(ValueError):
                    self.stream._decode_depth_message(frame)

    def test_depth_decoder_accepts_case_insensitive_configured_symbol(self):
        event = self.stream._decode_depth_message(
            '{"e":"depthUpdate","s":"btcusdt","U":100,"u":101,"pu":99,"b":[],"a":[]}'
        )
        self.assertEqual(event["s"], "btcusdt")

    def test_collector_rejects_wrong_symbol_or_event_type(self):
        self._prime_synchronized_book()
        class FakeWebSocket:
            def __init__(self, messages):
                self.messages = messages

            def __aiter__(self):
                async def iterate():
                    for message in self.messages:
                        yield message
                return iterate()

        invalid_frames = (
            '{"e":"depthUpdate","s":"ETHUSDT","U":100,"u":101,"pu":99,"b":[],"a":[]}',
            '{"e":"aggTrade","s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[],"a":[]}',
        )

        async def run_collector():
            queues = []
            for frame in invalid_frames:
                queue = asyncio.Queue()
                await self.stream._collect_depth_events(FakeWebSocket([frame]), queue)
                queues.append(queue)
            return queues

        queues = asyncio.run(run_collector())
        self.assertEqual(self.stream.messages_received, 2)
        self.assertEqual(self.stream.invalid_depth_message_count, 2)
        for queue in queues:
            self.assertIsNone(queue.get_nowait())
            self.assertTrue(queue.empty())
        self.assertFalse(self.stream.synchronized)
        self.assertIsNone(self.stream.synchronized_since)
        with patch("app.market_data.backend_stream.time.time", return_value=100.5):
            self.assertIsNone(asyncio.run(self.stream.get_order_book()))

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
                FakeWebSocket(['{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[],"a":[]}', "{broken-json"]),
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
                FakeWebSocket(['{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[],"a":[]}']),
                queue,
            )
            return await queue.get(), await queue.get()

        event, sentinel = asyncio.run(run_collector())
        self.assertEqual(event["u"], 101)
        self.assertIsNone(sentinel)
        self.assertIsNone(self.stream.last_error)

    def test_collector_overflow_discards_partial_buffer_and_signals_recovery(self):
        self._prime_synchronized_book()
        class FakeWebSocket:
            def __init__(self, messages):
                self.messages = messages

            def __aiter__(self):
                async def iterate():
                    for message in self.messages:
                        yield message
                return iterate()

        frame = '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[],"a":[]}'
        async def run_collector():
            queue = asyncio.Queue(maxsize=2)
            await self.stream._collect_depth_events(
                FakeWebSocket([frame, frame, frame]),
                queue,
            )
            return queue

        queue = asyncio.run(run_collector())
        self.assertEqual(self.stream.messages_received, 3)
        self.assertEqual(self.stream.snapshot_buffer_overflow_count, 1)
        self.assertEqual(queue.qsize(), 1)
        self.assertIsNone(queue.get_nowait())
        self.assertTrue(queue.empty())
        self.assertEqual(
            self.stream.last_error,
            "Depth event buffer overflow; reconnecting for fresh snapshot",
        )
        self.assertFalse(self.stream.synchronized)
        self.assertIsNone(self.stream.synchronized_since)
        with patch("app.market_data.backend_stream.time.time", return_value=100.5):
            self.assertIsNone(asyncio.run(self.stream.get_order_book()))

    def test_collector_normal_close_invalidates_synchronized_book(self):
        self._prime_synchronized_book()

        class FakeWebSocket:
            def __aiter__(self):
                async def iterate():
                    if False:
                        yield None
                return iterate()

        async def run_collector():
            queue = asyncio.Queue()
            await self.stream._collect_depth_events(FakeWebSocket(), queue)
            return await queue.get()

        sentinel = asyncio.run(run_collector())
        self.assertIsNone(sentinel)
        self.assertFalse(self.stream.synchronized)
        self.assertIsNone(self.stream.synchronized_since)
        with patch("app.market_data.backend_stream.time.time", return_value=100.5):
            self.assertIsNone(asyncio.run(self.stream.get_order_book()))

    def test_snapshot_bridge_not_synchronized_after_collector_has_ended(self):
        frame = '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[["99.5","1"]],"a":[]}'
        snapshot = {
            "lastUpdateId": 100,
            "bids": [["100", "2"]],
            "asks": [["101", "3"]],
        }

        class FakeWebSocket:
            def __aiter__(self):
                async def iterate():
                    yield frame
                return iterate()

        class FakeConnection:
            async def __aenter__(self):
                return FakeWebSocket()
            async def __aexit__(self, exc_type, exc, tb):
                return False

        async def delayed_snapshot():
            await asyncio.sleep(0)
            return snapshot

        async def run_connection():
            with patch("app.market_data.backend_stream.websockets.connect", return_value=FakeConnection()), \
                 patch.object(self.stream, "_fetch_snapshot", new=AsyncMock(side_effect=delayed_snapshot)):
                await self.stream._connect_and_sync()

        asyncio.run(run_connection())
        self.assertFalse(self.stream.synchronized)
        self.assertIsNone(self.stream.synchronized_since)
        self.assertIsNone(asyncio.run(self.stream.get_order_book()))

    def test_snapshot_bridge_rechecks_collector_after_lock_wait(self):
        frame = '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[["99.5","1"]],"a":[]}'
        snapshot = {
            "lastUpdateId": 100,
            "bids": [["100", "2"]],
            "asks": [["101", "3"]],
        }
        collector_release = asyncio.Event()
        iterator_finished = asyncio.Event()
        collector_tasks = []
        original_create_task = asyncio.create_task

        class RaceLock:
            def __init__(self):
                self.enter_count = 0

            async def __aenter__(self):
                self.enter_count += 1
                if self.enter_count == 2:
                    # Simulate the collector ending while the consumer waits
                    # to reacquire the book lock after its pre-lock check.
                    collector_release.set()
                    await iterator_finished.wait()
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeWebSocket:
            def __aiter__(self):
                async def iterate():
                    try:
                        yield frame
                        await collector_release.wait()
                    finally:
                        iterator_finished.set()
                return iterate()

        class FakeConnection:
            async def __aenter__(self):
                return FakeWebSocket()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        def capture_collector_task(coro):
            task = original_create_task(coro)
            collector_tasks.append(task)
            return task

        async def run_connection():
            self.stream._lock = RaceLock()
            with patch("app.market_data.backend_stream.websockets.connect", return_value=FakeConnection()), \
                 patch.object(self.stream, "_fetch_snapshot", new=AsyncMock(return_value=snapshot)), \
                 patch("app.market_data.backend_stream.asyncio.create_task", side_effect=capture_collector_task):
                await self.stream._connect_and_sync()

        asyncio.run(run_connection())
        self.assertEqual(len(collector_tasks), 1)
        self.assertTrue(collector_tasks[0].done())
        self.assertFalse(self.stream.synchronized)
        self.assertIsNone(self.stream.synchronized_since)
        self.assertEqual(self.stream.last_update_id, 100)
        self.assertEqual(self.stream.bids, {100.0: 2.0})
        self.assertEqual(self.stream.asks, {101.0: 3.0})
        self.assertEqual(self.stream.sequence_gap_count, 0)
        self.assertEqual(
            self.stream.last_error,
            "WebSocket ended during snapshot synchronization",
        )
        self.assertIsNone(asyncio.run(self.stream.get_order_book()))

    def test_snapshot_buffer_is_bounded_and_overflow_forces_recovery(self):
        self.assertEqual(SNAPSHOT_BUFFER_MAX_EVENTS, 1000)

        class FakeWebSocket:
            def __init__(self, messages):
                self.messages = messages

            def __aiter__(self):
                async def iterate():
                    for message in self.messages:
                        yield message
                return iterate()

        frame = '{"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"pu":99,"b":[],"a":[]}'
        async def run_collector():
            queue = asyncio.Queue(maxsize=2)
            await self.stream._collect_depth_events(
                FakeWebSocket([frame, frame, frame]),
                queue,
            )
            return queue

        queue = asyncio.run(run_collector())
        self.assertEqual(self.stream.messages_received, 3)
        self.assertEqual(self.stream.snapshot_buffer_overflow_count, 1)
        self.assertEqual(queue.qsize(), 1)
        self.assertIsNone(queue.get_nowait())
        self.assertTrue(queue.empty())
        self.assertEqual(
            self.stream.last_error,
            "Depth event buffer overflow; reconnecting for fresh snapshot",
        )

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


    def test_feed_diagnostics_error_count_counts_status_schema_issues_once(self):
        adapters = [
            {"exchange": "valid", "connected": True, "enabled": True, "last_error": None},
            {"exchange": "legacy", "connected": False, "last_error": None},
            {"exchange": "bad_connected", "connected": "true", "enabled": True},
            {"exchange": "bad_enabled", "connected": True, "enabled": 1},
            {"exchange": "missing_connected", "enabled": True},
            {"exchange": "reported_error", "connected": True, "last_error": "timeout"},
            None,
        ]
        self.assertEqual(main._feed_diagnostics_error_count({"exchanges": adapters}), 5)

    def test_feed_diagnostics_error_count_flags_malformed_containers(self):
        for status in (None, "invalid", {"exchanges": "not-a-list"}):
            with self.subTest(status=status):
                self.assertEqual(main._feed_diagnostics_error_count(status), 1)

    def test_feed_health_counts_require_boolean_connection_and_skip_malformed_records(self):
        adapters = [
            None,
            "not-an-adapter",
            [],
            {"exchange": "string-true", "symbol": "BTCUSDT", "connected": "true", "last_message_age_seconds": 0.1},
            {"exchange": "integer-one", "symbol": "BTCUSDT", "connected": 1, "last_message_age_seconds": 0.1},
            {"exchange": "valid", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 0.1},
        ]
        result = main._feed_health_counts(
            {"exchanges": adapters},
            {"stale_after_seconds": 3.0, "books": {
                "valid:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None, "age_seconds": 0.2, "best_bid": 100.0, "best_ask": 101.0},
            }},
        )
        self.assertEqual(result["fresh_message_feed_count"], 1)
        self.assertEqual(result["healthy_feed_count"], 1)

    def test_fresh_synchronized_book_requires_valid_two_sided_top_of_book(self):
        base = {
            "synchronized": True, "stale": False, "integrity_error": None,
            "age_seconds": 0.2, "best_bid": 100.0, "best_ask": 101.0,
        }
        self.assertTrue(main._is_fresh_synchronized_book(base, 3.0))
        invalid_books = (
            {**base, "best_bid": None},
            {**base, "best_ask": None},
            {**base, "best_bid": True},
            {**base, "best_ask": float("nan")},
            {**base, "best_bid": float("inf")},
            {**base, "best_bid": 0},
            {**base, "best_bid": -1},
            {**base, "best_bid": 101.0, "best_ask": 101.0},
            {**base, "best_bid": 102.0, "best_ask": 101.0},
            {**base, "best_bid": "invalid"},
            {**base, "best_ask": ""},
        )
        for book in invalid_books:
            with self.subTest(book=book):
                self.assertFalse(main._is_fresh_synchronized_book(book, 3.0))

    def test_feed_health_counts_return_zero_for_malformed_containers(self):
        for exchange_connections, unified_market_data in (
            (None, None),
            ("invalid", {}),
            ({"exchanges": "not-a-list"}, {"books": []}),
        ):
            with self.subTest(exchange_connections=exchange_connections):
                result = main._feed_health_counts(exchange_connections, unified_market_data)
                self.assertEqual(result["fresh_message_feed_count"], 0)
                self.assertEqual(result["healthy_feed_count"], 0)

    def test_feed_health_summary_requires_boolean_enabled_when_present(self):
        adapters = [
            {"exchange": "enabled_true", "symbol": "BTCUSDT", "enabled": True, "connected": True, "last_message_age_seconds": 0.2},
            {"exchange": "legacy", "symbol": "BTCUSDT", "connected": True, "last_message_age_seconds": 0.2},
            {"exchange": "disabled", "symbol": "BTCUSDT", "enabled": False, "connected": True, "last_message_age_seconds": 0.2},
            {"exchange": "null_enabled", "symbol": "BTCUSDT", "enabled": None, "connected": True, "last_message_age_seconds": 0.2},
            {"exchange": "string_true", "symbol": "BTCUSDT", "enabled": "true", "connected": True, "last_message_age_seconds": 0.2},
            {"exchange": "string_false", "symbol": "BTCUSDT", "enabled": "false", "connected": True, "last_message_age_seconds": 0.2},
            {"exchange": "integer_one", "symbol": "BTCUSDT", "enabled": 1, "connected": True, "last_message_age_seconds": 0.2},
            {"exchange": "integer_zero", "symbol": "BTCUSDT", "enabled": 0, "connected": True, "last_message_age_seconds": 0.2},
        ]
        books = {
            "enabled_true:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None, "age_seconds": 0.2, "best_bid": 100.0, "best_ask": 101.0},
            "legacy:BTCUSDT": {"synchronized": True, "stale": False, "integrity_error": None, "age_seconds": 0.2, "best_bid": 100.0, "best_ask": 101.0},
        }
        result = main._feed_health_counts(
            {"exchanges": adapters},
            {"stale_after_seconds": 3.0, "books": books},
        )
        self.assertEqual(result["fresh_message_feed_count"], 2)
        self.assertEqual(result["healthy_feed_count"], 2)


if __name__ == "__main__":
    unittest.main()
