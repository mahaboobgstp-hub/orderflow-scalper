import unittest
from unittest.mock import patch
from app.services.absorption_detector import AbsorptionLiquidityDetector


def book(**changes):
    value={"exchange":"bybit","symbol":"BTCUSDT","bids":[[100.0,10.0],[99.9,8.0]],
        "asks":[[100.1,10.0],[100.2,8.0]],"synchronized":True,"stale":False,"age_seconds":0.2,"integrity_error":None}
    value.update(changes); return value


def trades(side="buy",qty=1.0,count=8,price=100.05):
    return [{"side":side,"quantity":qty,"price":price,"received_timestamp_ms":int(__import__("time").time()*1000)} for _ in range(count)]


class Phase6DetectorTests(unittest.TestCase):
    def _fixed_movement_result(self, side, movement_pct):
        baseline_mid = 100.05
        current_mid = baseline_mid * (1.0 + movement_pct / 100.0)
        timestamp_ms = 1_000_000
        detector = AbsorptionLiquidityDetector()
        tape = [
            {"side": side, "quantity": 1.0, "price": 100.05,
             "received_timestamp_ms": timestamp_ms}
            for _ in range(8)
        ]

        def book_at(mid):
            return book(
                bids=[[mid - 0.05, 10.0], [mid - 0.15, 8.0]],
                asks=[[mid + 0.05, 10.0], [mid + 0.15, 8.0]],
            )

        with patch("app.services.absorption_detector.time.time", return_value=timestamp_ms / 1000.0):
            detector.analyze(book_at(baseline_mid), tape, 15)
            return detector.analyze(book_at(current_mid), tape, 15)

    def test_adverse_midpoint_movement_reduces_both_absorption_scores(self):
        buy = self._fixed_movement_result("buy", -0.05)
        sell = self._fixed_movement_result("sell", 0.05)
        self.assertAlmostEqual(buy["metrics"]["buy_price_progress_pct"], -0.05, places=6)
        self.assertAlmostEqual(sell["metrics"]["sell_price_progress_pct"], -0.05, places=6)
        self.assertAlmostEqual(buy["metrics"]["buy_absorption_score"], 0.5, places=6)
        self.assertAlmostEqual(sell["metrics"]["sell_absorption_score"], 0.5, places=6)

    def test_favorable_progress_boundary_zeroes_scores_for_both_sides(self):
        buy = self._fixed_movement_result("buy", 0.10)
        sell = self._fixed_movement_result("sell", -0.10)
        self.assertAlmostEqual(buy["metrics"]["buy_price_progress_pct"], 0.10, places=6)
        self.assertAlmostEqual(sell["metrics"]["sell_price_progress_pct"], 0.10, places=6)
        self.assertEqual(buy["metrics"]["buy_absorption_score"], 0.0)
        self.assertEqual(sell["metrics"]["sell_absorption_score"], 0.0)

    def test_sell_progress_uses_same_prior_mid_baseline_as_buy(self):
        result = self._fixed_movement_result("sell", -0.05)
        self.assertAlmostEqual(result["metrics"]["sell_price_progress_pct"], 0.05, places=6)

    def test_high_aggressive_buy_with_limited_progress_is_absorption_candidate(self):
        detector=AbsorptionLiquidityDetector()
        detector.analyze(book(),trades("buy"),15)
        result=detector.analyze(book(),trades("buy"),15)
        self.assertEqual(result["classification"],"POSSIBLE_BUY_ABSORPTION")
        self.assertTrue(result["metrics"]["buy_absorption_candidate"])
        self.assertEqual(result["metrics"]["aggressive_buy_quantity"],8.0)

    def test_sell_side_absorption_candidate(self):
        detector=AbsorptionLiquidityDetector()
        detector.analyze(book(),trades("sell"),15)
        result=detector.analyze(book(),trades("sell"),15)
        self.assertEqual(result["classification"],"POSSIBLE_SELL_ABSORPTION")
        self.assertTrue(result["metrics"]["sell_absorption_candidate"])

    def test_first_sample_does_not_infer_absorption_without_temporal_baseline(self):
        result=AbsorptionLiquidityDetector().analyze(book(),trades("buy"),15)
        self.assertEqual(result["classification"],"NO_CLEAR_ABSORPTION")
        self.assertEqual(result["metrics"]["buy_absorption_score"],0.0)

    def test_buy_and_sell_progress_are_temporal_and_directional(self):
        detector=AbsorptionLiquidityDetector()
        detector.analyze(book(),trades("buy"),15)
        up=detector.analyze(book(bids=[[100.1,10],[100.0,8]],asks=[[100.2,10],[100.3,8]]),trades("buy"),15)
        self.assertGreater(up["metrics"]["buy_price_progress_pct"],0)
        self.assertLess(up["metrics"]["sell_price_progress_pct"],0.0)
        down=detector.analyze(book(bids=[[99.9,10],[99.8,8]],asks=[[100.0,10],[100.1,8]]),trades("sell"),15)
        self.assertGreater(down["metrics"]["sell_price_progress_pct"],0)
        self.assertLess(down["metrics"]["buy_price_progress_pct"],0.0)

    def test_no_clear_absorption_when_tape_below_minimum(self):
        result=AbsorptionLiquidityDetector().analyze(book(),trades(count=2),15)
        self.assertEqual(result["classification"],"NO_CLEAR_ABSORPTION")
        self.assertEqual(result["trade_count"],2)

    def test_refuses_unsynced_and_stale_book(self):
        detector=AbsorptionLiquidityDetector()
        with self.assertRaisesRegex(ValueError,"unsynchronized"):
            detector.analyze(book(synchronized=False),trades())
        with self.assertRaisesRegex(ValueError,"stale"):
            detector.analyze(book(stale=True),trades())

    def test_refuses_invalid_book(self):
        with self.assertRaisesRegex(ValueError,"Crossed"):
            AbsorptionLiquidityDetector().analyze(book(bids=[[100.2,2]],asks=[[100.1,3]]),trades())

    def test_liquidity_changes_need_two_samples(self):
        detector=AbsorptionLiquidityDetector()
        first=detector.analyze(book(),trades())
        self.assertIsNone(first["liquidity_observation"]["replenishment"])
        second=detector.analyze(book(bids=[[100.0,14.0],[99.9,8.0]]),trades())
        self.assertTrue(second["liquidity_observation"]["replenishment"]["bid_replenished"])

    def test_trade_flow_summary_and_diagnostics(self):
        result=AbsorptionLiquidityDetector().analyze(book(),trades("buy",count=7),15)
        self.assertIn("flow_exhaustion",result)
        self.assertIn("quality",result)
        self.assertIn("not an entry",result["diagnostics"][4].lower())


    def test_rejects_negative_and_nonfinite_book_age(self):
        detector=AbsorptionLiquidityDetector()
        for age in (-0.01, float("nan"), float("inf"), float("-inf")):
            with self.subTest(age=age):
                with self.assertRaisesRegex(ValueError, "age"):
                    detector.analyze(book(age_seconds=age),trades())

    def test_rejects_non_numeric_book_age(self):
        with self.assertRaisesRegex(ValueError, "age"):
            AbsorptionLiquidityDetector().analyze(book(age_seconds="not-a-number"),trades())

    def test_rejects_nonfinite_detector_configuration(self):
        for value in (float("nan"),float("inf"),float("-inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError,"finite"):
                    AbsorptionLiquidityDetector(absorption_threshold=value)
                with self.assertRaisesRegex(ValueError,"finite"):
                    AbsorptionLiquidityDetector(max_book_age_seconds=value)

    def test_rejects_nonfinite_lookback(self):
        detector=AbsorptionLiquidityDetector()
        for lookback in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(lookback=lookback):
                with self.assertRaisesRegex(ValueError, "Lookback"):
                    detector.analyze(book(),trades(),lookback_seconds=lookback)

    def test_filters_invalid_trade_fields_and_out_of_window_timestamps(self):
        detector=AbsorptionLiquidityDetector()
        now_ms=int(__import__("time").time()*1000)
        valid=trades("buy",count=2)
        invalid=[
            {"side":"buy","quantity":1,"price":0,"received_timestamp_ms":now_ms},
            {"side":"buy","quantity":-1,"price":100,"received_timestamp_ms":now_ms},
            {"side":"buy","quantity":float("nan"),"price":100,"received_timestamp_ms":now_ms},
            {"side":"unknown","quantity":1,"price":100,"received_timestamp_ms":now_ms},
            {"side":"buy","quantity":1,"price":100,"received_timestamp_ms":now_ms-60000},
            {"side":"sell","quantity":1,"price":100,"received_timestamp_ms":now_ms+10000},
            {"side":"buy","quantity":1,"price":100,"received_timestamp_ms":"bad"},
        ]
        result=detector.analyze(book(),valid+invalid,15)
        self.assertEqual(result["trade_count"],2)
        self.assertEqual(result["metrics"]["aggressive_buy_quantity"],2.0)

    def test_flow_exhaustion_uses_timestamp_order_not_input_order(self):
        detector=AbsorptionLiquidityDetector()
        now_ms=int(__import__("time").time()*1000)
        late=[{"side":"buy","quantity":1,"price":100.05,"received_timestamp_ms":now_ms-100+i} for i in range(3)]
        early=[{"side":"buy","quantity":10,"price":100.05,"received_timestamp_ms":now_ms-200+i} for i in range(3)]
        # Deliberately pass later trades before earlier ones.
        result=detector.analyze(book(),late+early,15)
        self.assertEqual(result["flow_exhaustion"],"FLOW_WEAKENING")

    def test_absorption_requires_baseline_within_lookback(self):
        detector=AbsorptionLiquidityDetector()
        detector.analyze(book(),trades("buy"),lookback_seconds=1)
        # Simulate a previous observation older than the requested lookback.
        detector._history["bybit:BTCUSDT"][-1]["timestamp"]-=2000
        result=detector.analyze(book(),trades("buy"),lookback_seconds=1)
        self.assertEqual(result["classification"],"NO_CLEAR_ABSORPTION")
        self.assertEqual(result["metrics"]["buy_absorption_score"],0.0)

if __name__=="__main__":
    unittest.main()
