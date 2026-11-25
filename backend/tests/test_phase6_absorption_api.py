import asyncio
import unittest
from fastapi import HTTPException

from app.main import app, analyze_absorption
from app.services.absorption_detector import AbsorptionLiquidityDetector


def normalized_book(**overrides):
    data={
        "exchange":"bybit","symbol":"BTCUSDT","bids":[[100.0,10.0],[99.9,8.0]],
        "asks":[[100.1,10.0],[100.2,8.0]],"synchronized":True,"stale":False,
        "age_seconds":0.2,"integrity_error":None,
    }
    data.update(overrides)
    return data


class FakeMarketData:
    def __init__(self, book=None, tape=None):
        self.book=book
        self.tape=tape or []

    def get_book(self, exchange, symbol):
        return self.book

    def get_recent_trades(self, exchange, symbol, limit):
        return self.tape[:limit]


class Phase6ApiTests(unittest.TestCase):
    def call_route(self, exchange="bybit", symbol="BTCUSDT", lookback=15, limit=500):
        return asyncio.run(analyze_absorption(exchange,symbol,lookback,limit))

    def test_absorption_route_returns_expected_read_only_shape(self):
        fake=FakeMarketData(normalized_book(),[
            {"side":"buy","quantity":1.0,"price":100.05,"received_timestamp_ms":int(__import__("time").time()*1000)}
        ]*8)
        with unittest.mock.patch.object(app.state,"unified_market_data",fake,create=True), \
             unittest.mock.patch.object(app.state,"absorption_detector",AbsorptionLiquidityDetector(),create=True):
            result=self.call_route()
        self.assertEqual(result["detector"],"phase6_absorption_liquidity_behavior")
        self.assertEqual(result["exchange"],"bybit")
        self.assertEqual(result["symbol"],"BTCUSDT")
        self.assertIn("metrics",result)
        self.assertIn("classification",result)
        self.assertIn("liquidity_observation",result)
        self.assertIn("quality",result)
        self.assertIn("diagnostics",result)

    def test_absorption_route_rejects_unknown_exchange_and_missing_book(self):
        with unittest.mock.patch.object(app.state,"unified_market_data",FakeMarketData(None),create=True), \
             unittest.mock.patch.object(app.state,"absorption_detector",AbsorptionLiquidityDetector(),create=True):
            with self.assertRaises(HTTPException) as unknown:
                self.call_route(exchange="invalid")
            self.assertEqual(unknown.exception.status_code,400)
            with self.assertRaises(HTTPException) as missing:
                self.call_route()
            self.assertEqual(missing.exception.status_code,404)

    def test_absorption_route_maps_detector_safety_rejection_to_422(self):
        fake=FakeMarketData(normalized_book(synchronized=False),[])
        with unittest.mock.patch.object(app.state,"unified_market_data",fake,create=True), \
             unittest.mock.patch.object(app.state,"absorption_detector",AbsorptionLiquidityDetector(),create=True):
            with self.assertRaises(HTTPException) as rejected:
                self.call_route()
        self.assertEqual(rejected.exception.status_code,422)


if __name__ == "__main__":
    unittest.main()
