import unittest

from app.market_data.backend_stream import BinanceOrderBookStream


class BinanceDepthEventIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.stream = BinanceOrderBookStream("BTCUSDT")
        self.stream._load_snapshot({
            "lastUpdateId": 100,
            "bids": [["100", "2"], ["99", "3"]],
            "asks": [["101", "4"], ["102", "5"]],
        })

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
        self.assertEqual(sorted(stream.bids, reverse=True), [100, 99, 98, 97, 96])
        self.assertEqual(sorted(stream.asks), [101, 102, 103, 104, 105])
        self.assertEqual(len(stream.bids), 5)
        self.assertEqual(len(stream.asks), 5)

        self.assertTrue(stream._apply_event({
            "U": 101, "u": 102,
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
            "U": 101, "u": 102,
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
            "U": 101, "u": 102,
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
            {"U": 101, "u": 102, "b": [[True, "1"]], "a": []},
            {"U": 101, "u": 102, "b": [["99", True]], "a": []},
            {"U": 101, "u": 102, "b": [], "a": [["101", False]]},
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
            self.stream._apply_event({"U": 101, "u": 102, "b": [], "a": []})
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.last_update_id, before_update_id)
        self.assertEqual(self.stream.invalid_depth_message_count, 1)

    def test_one_sided_depth_event_is_valid_and_counted_as_applied(self):
        before_asks = dict(self.stream.asks)
        self.assertTrue(self.stream._apply_event({"U": 101, "u": 102, "b": [["99.5", "7"]], "a": []}))
        self.assertEqual(self.stream.bids[99.5], 7.0)
        self.assertEqual(self.stream.asks, before_asks)
        self.assertEqual(self.stream.invalid_depth_message_count, 0)

    def test_valid_two_sided_depth_event_applies_atomically(self):
        event = {
            "U": 101, "u": 102,
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
            "U": 101, "u": 102,
            "b": [["99.5", "7", "extra"]],
            "a": [],
        }
        with self.assertRaisesRegex(ValueError, "malformed level"):
            self.stream._apply_event(event)
        self.assertEqual(self.stream.bids, before_bids)
        self.assertEqual(self.stream.asks, before_asks)


if __name__ == "__main__":
    unittest.main()
