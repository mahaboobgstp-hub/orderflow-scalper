import unittest

from app.services.imbalance_detector import OrderBookImbalanceDetector


def sample_book(**overrides):
    book = {
        "exchange": "bybit",
        "symbol": "BTCUSDT",
        "bids": [[100.0, 10.0], [99.9, 8.0], [99.8, 6.0]],
        "asks": [[100.1, 2.0], [100.2, 2.0], [100.3, 1.0]],
        "synchronized": True,
        "stale": False,
        "age_seconds": 0.2,
        "integrity_error": None,
    }
    book.update(overrides)
    return book


class ImbalanceDetectorTests(unittest.TestCase):
    def test_buy_pressure_with_weighted_levels(self):
        detector = OrderBookImbalanceDetector()
        result = detector.analyze(sample_book(), levels=3)
        self.assertEqual(result["classification"], "BUY_PRESSURE")
        self.assertGreater(result["metrics"]["weighted_imbalance"], 0)
        self.assertGreater(result["metrics"]["raw_imbalance"], 0)
        self.assertEqual(result["levels_used"]["bids"], 3)
        self.assertEqual(result["levels_used"]["asks"], 3)

    def test_sell_pressure(self):
        detector = OrderBookImbalanceDetector()
        book = sample_book(
            bids=[[100.0, 1.0], [99.9, 1.0]],
            asks=[[100.1, 10.0], [100.2, 8.0]],
        )
        self.assertEqual(detector.analyze(book, 2)["classification"], "SELL_PRESSURE")

    def test_neutral_classification(self):
        detector = OrderBookImbalanceDetector()
        book = sample_book(bids=[[100, 5], [99.9, 5]], asks=[[100.1, 5], [100.2, 5]])
        self.assertEqual(detector.analyze(book, 2)["classification"], "NEUTRAL")

    def test_refuses_unsynchronized_book(self):
        with self.assertRaisesRegex(ValueError, "unsynchronized"):
            OrderBookImbalanceDetector().analyze(sample_book(synchronized=False))

    def test_refuses_stale_book(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            OrderBookImbalanceDetector().analyze(sample_book(stale=True))

    def test_refuses_old_book(self):
        with self.assertRaisesRegex(ValueError, "age"):
            OrderBookImbalanceDetector().analyze(sample_book(age_seconds=5.0))

    def test_refuses_crossed_book(self):
        book = sample_book(bids=[[100.2, 1]], asks=[[100.1, 1]])
        with self.assertRaisesRegex(ValueError, "Crossed"):
            OrderBookImbalanceDetector().analyze(book)

    def test_persistence_history_and_pressure_change(self):
        detector = OrderBookImbalanceDetector()
        book = sample_book()
        first = detector.analyze(book, 3)
        second = detector.analyze(book, 3)
        self.assertEqual(second["persistence"]["samples"], 2)
        self.assertGreater(second["persistence"]["current_pressure_persistence"], 0)
        self.assertIsNotNone(second["persistence"]["pressure_change_from_previous"])
        self.assertIn("score", second["quality"])

    def test_level_count_clamped(self):
        result = OrderBookImbalanceDetector().analyze(sample_book(), levels=999)
        self.assertEqual(result["levels_requested"], 20)
        self.assertEqual(result["levels_used"]["bids"], 3)

    def test_weighted_imbalance_calculation_is_correct(self):
        detector = OrderBookImbalanceDetector()
        book = sample_book(
            bids=[[100.0, 4.0], [99.9, 2.0]],
            asks=[[100.1, 2.0], [100.2, 2.0]],
        )
        result = detector.analyze(book, 2)
        metrics = result["metrics"]
        self.assertAlmostEqual(metrics["raw_imbalance"], 0.2, places=6)
        # Rank-decayed quantities: 4 + 2/2 = 5 vs 2 + 2/2 = 3.
        self.assertAlmostEqual(metrics["weighted_imbalance"], 0.25, places=6)
        self.assertEqual(result["classification"], "BUY_PRESSURE")

    def test_invalid_levels_are_ignored_safely(self):
        detector = OrderBookImbalanceDetector()
        book = sample_book(
            bids=[[100, 5], [99, 0], [98, "bad"], [97, float("nan")], [96, -2]],
            asks=[[101, 4], [102, 0], [103, float("inf")]],
        )
        result = detector.analyze(book, 5)
        self.assertEqual(result["levels_used"], {"bids": 1, "asks": 1})
        self.assertEqual(result["classification"], "NEUTRAL")

    def test_empty_or_invalid_sides_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Both bid and ask"):
            OrderBookImbalanceDetector().analyze(sample_book(bids=[]))
        with self.assertRaisesRegex(ValueError, "Both bid and ask"):
            OrderBookImbalanceDetector().analyze(sample_book(asks=[[0, 3], [100, -1]]))

    def test_history_is_separated_by_exchange_and_symbol(self):
        detector = OrderBookImbalanceDetector()
        first = detector.analyze(sample_book(), 3)
        other_symbol = detector.analyze(sample_book(symbol="ETHUSDT"), 3)
        other_exchange = detector.analyze(sample_book(exchange="binance"), 3)
        self.assertEqual(first["persistence"]["samples"], 1)
        self.assertEqual(other_symbol["persistence"]["samples"], 1)
        self.assertEqual(other_exchange["persistence"]["samples"], 1)
        self.assertEqual(detector.status()["tracked_streams"], 3)

    def test_threshold_is_clamped_to_supported_range(self):
        self.assertEqual(OrderBookImbalanceDetector(pressure_threshold=-10).pressure_threshold, 0.01)
        self.assertEqual(OrderBookImbalanceDetector(pressure_threshold=2).pressure_threshold, 0.95)


if __name__ == "__main__":
    unittest.main()
