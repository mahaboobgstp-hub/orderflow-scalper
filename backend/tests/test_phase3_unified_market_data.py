import asyncio
import json
import time
import unittest
from unittest.mock import patch

from app.market_data.unified_engine import UnifiedMarketDataEngine
from app.exchanges.public_adapters import BinancePublicAdapter, BinanceMarketAdapter, DeltaPublicAdapter, PublicExchangeAdapter
from app.exchanges.manager import BinanceMarketAdapter as ExportedBinanceMarketAdapter


def bybit_snapshot(u=10, seq=100, bids=None, asks=None, ts=None):
    data = {
        "s": "BTCUSDT",
        "b": bids if bids is not None else [["100", "2"], ["99", "1"]],
        "a": asks if asks is not None else [["101", "3"], ["102", "2"]],
        "u": u,
    }
    if seq is not None:
        data["seq"] = seq
    return {"topic": "orderbook.50.BTCUSDT", "type": "snapshot", "data": data, "ts": int(time.time() * 1000) if ts is None else ts}


def bybit_delta(u, seq=101, bids=None, asks=None, ts=None):
    data = {
        "s": "BTCUSDT",
        "b": bids if bids is not None else [],
        "a": asks if asks is not None else [],
        "u": u,
    }
    if seq is not None:
        data["seq"] = seq
    return {"topic": "orderbook.50.BTCUSDT", "type": "delta", "data": data, "ts": int(time.time() * 1000) if ts is None else ts}


class Tests(unittest.TestCase):
    def setUp(self):
        self.e = UnifiedMarketDataEngine()

    def test_bybit_snapshot_delta_contiguous(self):
        snapshot = self.e.process("bybit", bybit_snapshot(u=10))
        self.assertTrue(snapshot["synchronized"])
        delta = self.e.process("bybit", bybit_delta(11, bids=[["100", "0"], ["99", "4"]]))
        book = self.e.get_book("bybit", "BTCUSDT")
        self.assertTrue(delta["synchronized"])
        self.assertEqual(book["best_bid"], 99.0)
        self.assertEqual(book["sequence"], 11)

    def test_bybit_snapshot_replaces_previous_levels(self):
        self.e.process("bybit", bybit_snapshot(u=10))
        self.e.process("bybit", bybit_snapshot(u=1, seq=1, bids=[["98", "2"]], asks=[["99", "2"]]))
        book = self.e.get_book("bybit", "BTCUSDT")
        self.assertEqual(book["bids"], [[98.0, 2.0]])
        self.assertEqual(book["asks"], [[99.0, 2.0]])
        self.assertEqual(book["sequence"], 1)
        self.assertTrue(book["synchronized"])

    def test_bybit_old_or_duplicate_delta_is_ignored(self):
        self.e.process("bybit", bybit_snapshot(u=10))
        before = self.e.get_book("bybit", "BTCUSDT")
        for stale_u in (9, 10):
            result = self.e.process("bybit", bybit_delta(stale_u, bids=[["99", "9"]]))
            book = self.e.get_book("bybit", "BTCUSDT")
            self.assertEqual(result["type"], "book_delta_ignored")
            self.assertTrue(book["synchronized"])
            self.assertEqual(book["sequence"], 10)
            self.assertEqual(book["bids"], before["bids"])

    def test_bybit_update_gap_invalidates_and_requires_snapshot(self):
        self.e.process("bybit", bybit_snapshot(u=10))
        gap = self.e.process("bybit", bybit_delta(12, bids=[["99", "9"]]))
        self.assertTrue(gap["resync_required"])
        book = self.e.get_book("bybit", "BTCUSDT")
        self.assertFalse(book["synchronized"])
        self.assertTrue(book["stale"])
        self.assertEqual(book["bids"], [])
        blocked = self.e.process("bybit", bybit_delta(13, bids=[["99", "9"]]))
        self.assertTrue(blocked["resync_required"])
        self.assertFalse(self.e.get_book("bybit", "BTCUSDT")["synchronized"])
        recovered = self.e.process("bybit", bybit_snapshot(u=20, seq=200))
        self.assertTrue(recovered["synchronized"])
        next_delta = self.e.process("bybit", bybit_delta(21, seq=201, bids=[["100", "0"], ["99", "9"]]))
        self.assertTrue(next_delta["synchronized"])
        self.assertEqual(self.e.get_book("bybit", "BTCUSDT")["best_bid"], 99.0)

    def test_bybit_delta_u_one_requires_snapshot_reset(self):
        self.e.process("bybit", bybit_snapshot(u=10))
        reset = self.e.process("bybit", bybit_delta(1, bids=[["99", "9"]]))
        self.assertTrue(reset["resync_required"])
        book = self.e.get_book("bybit", "BTCUSDT")
        self.assertFalse(book["synchronized"])
        self.assertEqual(book["bids"], [])
        snapshot = self.e.process("bybit", bybit_snapshot(u=1, seq=1))
        self.assertTrue(snapshot["synchronized"])

    def test_bybit_delta_invalid_levels_are_atomic_and_invalidate(self):
        self.e.process("bybit", bybit_snapshot(u=10))
        result = self.e.process("bybit", bybit_delta(11, bids=[["99", "9"]], asks=[["101", "NaN"]]))
        self.assertTrue(result["resync_required"])
        book = self.e.get_book("bybit", "BTCUSDT")
        self.assertFalse(book["synchronized"])
        self.assertEqual(book["bids"], [])
        self.assertEqual(book["asks"], [])

    def test_bybit_crossed_delta_invalidates_book(self):
        self.e.process("bybit", bybit_snapshot(u=10))
        result = self.e.process("bybit", bybit_delta(11, bids=[["102", "2"]]))
        self.assertTrue(result["resync_required"])
        self.assertFalse(self.e.get_book("bybit", "BTCUSDT")["synchronized"])

    def test_bybit_crossed_snapshot_is_rejected(self):
        result = self.e.process("bybit", bybit_snapshot(u=10, bids=[["102", "2"]], asks=[["101", "3"]]))
        self.assertTrue(result["resync_required"])
        book = self.e.get_book("bybit", "BTCUSDT")
        self.assertFalse(book["synchronized"])
        self.assertEqual(book["bids"], [])
        self.assertEqual(book["asks"], [])

    def test_bybit_snapshot_rejects_invalid_sequence_or_levels(self):
        missing_u = {"topic": "orderbook.50.BTCUSDT", "type": "snapshot", "data": {"b": [["100", "2"]], "a": [["101", "2"]]}}
        self.assertTrue(self.e.process("bybit", missing_u)["resync_required"])
        for invalid in (True, 1.5, -1, "NaN"):
            with self.subTest(invalid=invalid):
                self.assertTrue(self.e.process("bybit", bybit_snapshot(u=invalid))["resync_required"])
        for invalid_levels in ([["NaN", "1"]], [["100", "Infinity"]], [[True, "2"]]):
            with self.subTest(invalid_levels=invalid_levels):
                bad = bybit_snapshot(u=10, bids=invalid_levels, asks=[["101", "1"]])
                self.assertTrue(self.e.process("bybit", bad)["resync_required"])

    def test_bybit_cross_sequence_regression_invalidates(self):
        self.e.process("bybit", bybit_snapshot(u=10, seq=100))
        result = self.e.process("bybit", bybit_delta(11, seq=99))
        self.assertTrue(result["resync_required"])
        self.assertFalse(self.e.get_book("bybit", "BTCUSDT")["synchronized"])

    def test_delta_before_snapshot_is_refused(self):
        result = self.e.process("bybit", bybit_delta(2, bids=[["99", "4"]]))
        self.assertTrue(result["resync_required"])
        self.assertFalse(self.e.get_book("bybit", "BTCUSDT")["synchronized"])

    def test_trade(self):
        result = self.e.process("bybit", {"topic": "publicTrade.BTCUSDT", "data": [{"s": "BTCUSDT", "p": "101", "v": "2", "S": "Buy"}]})
        self.assertEqual(result["side"], "buy")
        self.assertEqual(len(self.e.get_recent_trades("bybit", "BTCUSDT")), 1)

    def test_invalid_nonfinite_trade_is_rejected(self):
        for price, quantity in (("NaN", 1), ("Infinity", 1), (100, "Infinity"), (True, 1)):
            result = self.e.process("bybit", {"topic": "publicTrade.BTCUSDT", "data": [{"s": "BTCUSDT", "p": price, "v": quantity, "S": "Buy"}]})
            self.assertIsNone(result)
        self.assertEqual(self.e.get_recent_trades("bybit", "BTCUSDT"), [])

    def test_trade_activity_does_not_refresh_book_freshness(self):
        with patch("app.market_data.unified_engine.time.time", return_value=1000.0):
            self.e.process("bybit", bybit_snapshot(u=10))
        with patch("app.market_data.unified_engine.time.time", return_value=1004.0):
            self.e.process("bybit", {"topic": "publicTrade.BTCUSDT", "data": [{"s": "BTCUSDT", "p": "100", "v": "1", "S": "Buy"}]})
            book = self.e.get_book("bybit", "BTCUSDT")
        self.assertTrue(book["synchronized"])
        self.assertTrue(book["stale"])
        self.assertEqual(book["age_seconds"], 4.0)

    def test_binance_raw_diff_is_never_exposed_as_synchronized_book(self):
        result = self.e.process("binance", {"e": "depthUpdate", "s": "BTCUSDT", "U": 1, "u": 2, "b": [["10", "1"]], "a": [["11", "2"]]})
        book = self.e.get_book("binance", "BTCUSDT")
        self.assertFalse(result["synchronized"])
        self.assertFalse(book["synchronized"])
        self.assertEqual(book["bids"], [])
        self.assertEqual(book["asks"], [])

    def test_status_exposes_book_sequence_and_freshness(self):
        self.e.process("bybit", bybit_snapshot(u=7, seq=70, bids=[["100", "2"], ["99", "1"]], asks=[["101", "3"], ["102", "2"]]))
        status = self.e.get_status()
        book = status["books"]["bybit:BTCUSDT"]
        self.assertTrue(book["synchronized"])
        self.assertEqual(book["sequence"], 7)
        self.assertEqual(book["cross_sequence"], 70)
        self.assertEqual(book["best_bid"], 100.0)
        self.assertEqual(book["best_ask"], 101.0)
        self.assertEqual(book["spread"], 1.0)
        self.assertEqual(book["bid_depth_top10"], 3.0)
        self.assertEqual(book["ask_depth_top10"], 5.0)
        self.assertAlmostEqual(book["imbalance_top10"], -0.25)
        self.assertIsNotNone(book["age_seconds"])
        self.assertEqual(status["exchanges"]["bybit"]["messages_received"], 1)

    def test_status_marks_stale_book(self):
        with patch("app.market_data.unified_engine.time.time", return_value=1000.0):
            self.e.process("bybit", bybit_snapshot(u=1))
        self.e.stale_after_seconds = 0
        with patch("app.market_data.unified_engine.time.time", return_value=1001.0):
            self.assertTrue(self.e.get_status()["books"]["bybit:BTCUSDT"]["stale"])

    def test_bybit_book_requires_exchange_timestamp(self):
        event = bybit_snapshot(u=1)
        event.pop("ts")
        with patch("app.market_data.unified_engine.time.time", return_value=100.0):
            result = self.e.process("bybit", event)
        self.assertTrue(result["resync_required"])
        self.assertFalse(self.e.get_book("bybit", "BTCUSDT")["synchronized"])

    def test_bybit_exchange_timestamp_age_and_future_skew_boundaries(self):
        with patch("app.market_data.unified_engine.time.time", return_value=100.0):
            at_age_limit = self.e.process("bybit", bybit_snapshot(u=1, ts=97000))
            self.assertTrue(at_age_limit["synchronized"])
            at_future_limit = self.e.process("bybit", bybit_snapshot(u=2, ts=105000))
            self.assertTrue(at_future_limit["synchronized"])
            too_old = self.e.process("bybit", bybit_snapshot(u=3, ts=96999))
            self.assertTrue(too_old["resync_required"])
            self.assertFalse(self.e.get_book("bybit", "BTCUSDT")["synchronized"])
            too_far_future = self.e.process("bybit", bybit_snapshot(u=4, ts=105001))
            self.assertTrue(too_far_future["resync_required"])
            self.assertFalse(self.e.get_book("bybit", "BTCUSDT")["synchronized"])

    def test_delta_exchange_snapshot_and_delta(self):
        snapshot = {"type": "snapshot", "data": {"buy": [["100", "2"]], "sell": [["101", "3"]], "seq": 100}, "ts": int(time.time() * 1000)}
        self.assertTrue(self.e.process("delta", snapshot)["synchronized"])
        delta = {"type": "delta", "action": "update", "data": {"buy": [["100", "0"], ["99", "4"]], "sell": [], "seq": 101}, "ts": int(time.time() * 1000)}
        self.assertTrue(self.e.process("delta", delta)["synchronized"])
        self.assertEqual(self.e.get_book("delta", "BTCUSDT")["best_bid"], 99.0)

    def test_delta_exchange_crossed_update_invalidates(self):
        self.e.process("delta", {"type": "snapshot", "data": {"buy": [["100", "2"]], "sell": [["101", "3"]], "seq": 100}, "ts": int(time.time() * 1000)})
        result = self.e.process("delta", {"type": "delta", "action": "update", "data": {"buy": [["102", "1"]], "sell": [], "seq": 101}, "ts": int(time.time() * 1000)})
        self.assertTrue(result["resync_required"])
        self.assertFalse(self.e.get_book("delta", "BTCUSDT")["synchronized"])

    def test_delta_ob_updates_snapshot_and_incremental_sequence_with_symbol_alias(self):
        base = int(time.time() * 1_000_000)
        snapshot = {"type": "ob_updates", "action": "snapshot", "sy": "BTCUSD", "seq": 6199,
                    "b": [["100", "2"]], "a": [["101", "3"]], "ts": base}
        result = self.e.process("delta", snapshot)
        self.assertTrue(result["synchronized"])
        book = self.e.get_book("delta", "BTCUSD")
        self.assertTrue(book["synchronized"])
        self.assertEqual(book["sequence"], 6199)
        self.assertEqual(book["best_bid"], 100.0)
        self.assertEqual(book["best_ask"], 101.0)
        self.assertEqual(book["exchange_timestamp_ms"], base // 1000)

        update = {"type": "ob_updates", "action": "update", "sy": "BTCUSD", "seq": 6200,
                  "b": [["100", "0"], ["99", "4"]], "a": [["101", "0"], ["102", "3"]],
                  "ts": base + 1000}
        result = self.e.process("delta", update)
        self.assertTrue(result["synchronized"])
        book = self.e.get_book("delta", "BTCUSD")
        self.assertEqual(book["sequence"], 6200)
        self.assertEqual(book["best_bid"], 99.0)
        self.assertEqual(book["best_ask"], 102.0)

    def test_delta_ob_updates_gap_invalidates_and_requires_fresh_snapshot(self):
        base = int(time.time() * 1_000_000)
        self.e.process("delta", {"type": "ob_updates", "action": "snapshot", "sy": "BTCUSD",
                                 "seq": 1000, "b": [["100", "2"]], "a": [["101", "3"]], "ts": base})
        gap = self.e.process("delta", {"type": "ob_updates", "action": "update", "sy": "BTCUSD",
                                       "seq": 1002, "b": [["99", "4"]], "a": [], "ts": base + 1000})
        self.assertTrue(gap["resync_required"])
        book = self.e.get_book("delta", "BTCUSD")
        self.assertFalse(book["synchronized"])
        self.assertEqual(book["bids"], [])
        blocked = self.e.process("delta", {"type": "ob_updates", "action": "update", "sy": "BTCUSD",
                                           "seq": 1003, "b": [["99", "4"]], "a": [], "ts": base + 2000})
        self.assertTrue(blocked["resync_required"])
        recovered = self.e.process("delta", {"type": "ob_updates", "action": "snapshot", "sy": "BTCUSD",
                                            "seq": 2000, "b": [["100", "2"]], "a": [["101", "3"]], "ts": base + 3000})
        self.assertTrue(recovered["synchronized"])
        next_update = self.e.process("delta", {"type": "ob_updates", "action": "update", "sy": "BTCUSD",
                                               "seq": 2001, "b": [["100", "0"], ["99", "4"]], "a": [], "ts": base + 4000})
        self.assertTrue(next_update["synchronized"])
        self.assertEqual(self.e.get_book("delta", "BTCUSD")["best_bid"], 99.0)

    def test_delta_ob_updates_rejects_missing_sequence_and_error_action(self):
        missing = self.e.process("delta", {"type": "ob_updates", "action": "snapshot", "sy": "BTCUSD",
                                          "b": [["100", "2"]], "a": [["101", "3"]], "ts": int(time.time() * 1_000_000)})
        self.assertTrue(missing["resync_required"])
        error = self.e.process("delta", {"type": "ob_updates", "action": "error", "sy": "BTCUSD",
                                         "msg": "Snapshot load failed"})
        self.assertTrue(error["resync_required"])
        self.assertIn("Snapshot load failed", error["error"])

    def test_delta_ob_l2_snapshot_only_channel_is_not_accepted_as_synced(self):
        result = self.e.process("delta", {"type": "ob_l2", "sy": "BTCUSD",
                                         "b": [["100", "2"]], "a": [["101", "3"]]})
        self.assertTrue(result["resync_required"])
        book = self.e.get_book("delta", "BTCUSD")
        self.assertFalse(book["synchronized"])
        self.assertEqual(book["bids"], [])
        self.assertEqual(book["asks"], [])

    def test_delta_ob_updates_rejects_stale_exchange_timestamp(self):
        now_seconds = 1700000000.0
        stale_ts_us = (int(now_seconds * 1000) - 4000) * 1000
        stale_snapshot = {"type": "ob_updates", "action": "snapshot", "sy": "BTCUSD", "seq": 50,
                         "b": [["100", "2"]], "a": [["101", "3"]], "ts": stale_ts_us}
        with patch("app.market_data.unified_engine.time.time", return_value=now_seconds):
            result = self.e.process("delta", stale_snapshot)
        self.assertTrue(result["resync_required"])
        self.assertFalse(self.e.get_book("delta", "BTCUSD")["synchronized"])

    def test_delta_trade_buyer_role_maps_aggressor_side_and_microsecond_timestamps(self):
        base = 1700000000000000
        maker_buyer = {"type": "trades", "sy": "BTCUSD", "p": "100.5", "s": "2",
                      "r": "m", "t": base, "ts": base + 1234000}
        result = self.e.process("delta", maker_buyer)
        self.assertEqual(result["side"], "sell")
        self.assertEqual(result["symbol"], "BTCUSD")
        maker_buyer_trade = self.e.get_recent_trades("delta", "BTCUSD")[0]
        self.assertEqual(maker_buyer_trade["exchange_timestamp_ms"], base // 1000)
        self.assertEqual(maker_buyer_trade["quantity"], 2.0)

        taker_buyer = {**maker_buyer, "r": "t", "t": base + 5000}
        result = self.e.process("delta", taker_buyer)
        self.assertEqual(result["side"], "buy")
        recent = self.e.get_recent_trades("delta", "BTCUSD")
        self.assertEqual(recent[-1]["side"], "buy")
        self.assertEqual(recent[-1]["exchange_timestamp_ms"], (base + 5000) // 1000)


class _FakeWS:
    def __init__(self, payload):
        self.payload = payload

    async def __aiter__(self):
        yield json.dumps(self.payload)

class _CaptureWS:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


class _FakeConnection:
    def __init__(self, websocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _TestAdapter(PublicExchangeAdapter):
    async def _subscribe(self, websocket):
        return


class PublicAdapterResyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_delta_adapter_subscribes_to_sequenced_book_and_trade_channels(self):
        adapter = DeltaPublicAdapter(True)
        self.assertEqual(adapter.symbol, "BTCUSD")
        self.assertIn("testnet", adapter.url)
        ws = _CaptureWS()
        await adapter._subscribe(ws)
        payload = json.loads(ws.sent[0])
        channels = payload["payload"]["channels"]
        self.assertEqual([channel["name"] for channel in channels], ["ob_updates", "trades"])
        self.assertEqual([channel["symbols"] for channel in channels], [["BTCUSD"], ["BTCUSD"]])

    async def test_resync_required_callback_forces_disconnect(self):
        adapter = _TestAdapter("test", True, "wss://test.invalid", on_message=None)
        adapter._stop.clear()

        def callback(_exchange, _payload):
            adapter._stop.set()
            return {"resync_required": True, "error": "sequence gap test"}

        adapter.on_message = callback
        fake_connection = _FakeConnection(_FakeWS({"type": "delta"}))
        with patch("app.exchanges.public_adapters.websockets.connect", return_value=fake_connection):
            await adapter._run()
        self.assertFalse(adapter.connected)
        self.assertIn("sequence gap test", adapter.last_error)
        self.assertEqual(adapter.reconnect_count, 0)


class BinanceRoutedEndpointTests(unittest.TestCase):
    def test_depth_feed_uses_public_routed_endpoint(self):
        adapter = BinancePublicAdapter(True, symbol="BTCUSDT")
        self.assertEqual(adapter.url, "wss://fstream.binance.com/public/stream?streams=btcusdt@depth@100ms")
        self.assertEqual(adapter.feed_type, "depth")

    def test_aggregate_trades_use_market_routed_endpoint(self):
        adapter = BinanceMarketAdapter(True, symbol="BTCUSDT")
        self.assertEqual(adapter.url, "wss://fstream.binance.com/market/stream?streams=btcusdt@aggTrade")
        self.assertEqual(adapter.feed_type, "aggregate_trades")
        self.assertIs(ExportedBinanceMarketAdapter, BinanceMarketAdapter)

if __name__ == "__main__":
    unittest.main()
