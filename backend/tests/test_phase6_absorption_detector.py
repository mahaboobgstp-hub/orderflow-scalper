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
        self.assertLess(up["metrics"]["sell_price_progress_pct"],0)
        down=detector.analyze(book(bids=[[99.9,10],[99.8,8]],asks=[[100.0,10],[100.1,8]]),trades("sell"),15)
        self.assertGreater(down["metrics"]["sell_price_progress_pct"],0)
        self.assertLess(down["metrics"]["buy_price_progress_pct"],0)

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
        self.assertTrue(any("not an entry" in item.lower() for item in result["diagnostics"]))


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

    def test_absorption_requires_baseline_within_lookback(self):
        detector=AbsorptionLiquidityDetector()
        detector.analyze(book(),trades("buy"),lookback_seconds=1)
        # Simulate a previous observation older than the requested lookback.
        detector._history["bybit:BTCUSDT"][-1]["timestamp"]-=2000
        result=detector.analyze(book(),trades("buy"),lookback_seconds=1)
        self.assertEqual(result["classification"],"NO_CLEAR_ABSORPTION")
        self.assertEqual(result["metrics"]["buy_absorption_score"],0.0)


    @staticmethod
    def _fixed_tape(side, price, timestamp_ms, count=8, quantity=1.0):
        return [{"side":side,"price":price,"quantity":quantity,"received_timestamp_ms":timestamp_ms} for _ in range(count)]

    @staticmethod
    def _book_at_mid(mid):
        return book(bids=[[mid-0.05,10.0],[mid-0.15,8.0]],
                   asks=[[mid+0.05,10.0],[mid+0.15,8.0]])

    def _analyze_at(self, detector, test_book, tape, timestamp_ms):
        with patch("app.services.absorption_detector.time.time",return_value=timestamp_ms/1000.0):
            return detector.analyze(test_book,tape,lookback_seconds=15)

    def _progress_case(self, side, movement_pct):
        detector=AbsorptionLiquidityDetector()
        base_mid=100.05
        first_ts=1_000_000
        first_tape=self._fixed_tape(side,base_mid,first_ts)
        self._analyze_at(detector,self._book_at_mid(base_mid),first_tape,first_ts)
        second_ts=1_001_000
        target_mid=base_mid*(1.0+movement_pct/100.0)
        second_tape=self._fixed_tape(side,target_mid,second_ts)
        return self._analyze_at(detector,self._book_at_mid(target_mid),second_tape,second_ts)

    def test_signed_progress_and_abs_movement_score_thresholds_both_sides(self):
        cases=[
            ("buy",0.040,0.600,True,"POSSIBLE_BUY_ABSORPTION"),
            ("buy",0.041,0.590,False,"NO_CLEAR_ABSORPTION"),
            ("buy",-0.060,0.400,False,"NO_CLEAR_ABSORPTION"),
            ("buy",0.100,0.000,False,"NO_CLEAR_ABSORPTION"),
            ("sell",-0.040,0.600,True,"POSSIBLE_SELL_ABSORPTION"),
            ("sell",-0.041,0.590,False,"NO_CLEAR_ABSORPTION"),
            ("sell",0.060,0.400,False,"NO_CLEAR_ABSORPTION"),
            ("sell",-0.100,0.000,False,"NO_CLEAR_ABSORPTION"),
        ]
        for side,movement,expected_score,expected_candidate,expected_class in cases:
            with self.subTest(side=side,movement_pct=movement):
                result=self._progress_case(side,movement)
                metrics=result["metrics"]
                signed_progress=movement if side=="buy" else -movement
                score_key=f"{side}_absorption_score"
                candidate_key=f"{side}_absorption_candidate"
                progress_key=f"{side}_price_progress_pct"
                self.assertAlmostEqual(metrics[progress_key],signed_progress,places=5)
                self.assertAlmostEqual(metrics[score_key],expected_score,places=5)
                self.assertEqual(metrics[candidate_key],expected_candidate)
                self.assertEqual(result["classification"],expected_class)

    def test_vwap_vs_mid_sign_is_spatial_and_separate_from_temporal_progress(self):
        detector=AbsorptionLiquidityDetector()
        mid=100.05
        t0=1_000_000
        positive_tape=self._fixed_tape("buy",mid+0.02,t0,count=5)+self._fixed_tape("sell",mid-0.02,t0,count=5)
        first=self._analyze_at(detector,self._book_at_mid(mid),positive_tape,t0)
        t1=1_001_000
        negative_tape=self._fixed_tape("buy",mid-0.02,t1,count=5)+self._fixed_tape("sell",mid+0.02,t1,count=5)
        second=self._analyze_at(detector,self._book_at_mid(mid),negative_tape,t1)
        self.assertGreater(first["metrics"]["buy_vwap_vs_mid_pct"],0)
        self.assertGreater(first["metrics"]["sell_vwap_vs_mid_pct"],0)
        self.assertLess(second["metrics"]["buy_vwap_vs_mid_pct"],0)
        self.assertLess(second["metrics"]["sell_vwap_vs_mid_pct"],0)
        self.assertEqual(second["metrics"]["buy_price_progress_pct"],0.0)
        self.assertEqual(second["metrics"]["sell_price_progress_pct"],0.0)

    def test_thin_book_is_exposed_as_low_depth_not_silently_rejected(self):
        detector=AbsorptionLiquidityDetector()
        mid=100.05
        thin=self._book_at_mid(mid)
        thin["bids"]=[[100.0,0.001]]
        thin["asks"]=[[100.1,0.001]]
        t0=1_000_000
        first=self._fixed_tape("buy",mid,t0)
        self._analyze_at(detector,thin,first,t0)
        t1=1_001_000
        result=self._analyze_at(detector,thin,self._fixed_tape("buy",mid,t1),t1)
        self.assertEqual(result["metrics"]["top5_bid_depth"],0.001)
        self.assertEqual(result["metrics"]["top5_ask_depth"],0.001)
        self.assertTrue(result["metrics"]["buy_absorption_candidate"])

if __name__=="__main__":
    unittest.main()
