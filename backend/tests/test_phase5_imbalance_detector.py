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


if __name__ == "__main__":
    unittest.main()
