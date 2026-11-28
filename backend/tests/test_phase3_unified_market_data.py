import unittest
from unittest.mock import patch
from app.market_data.unified_engine import UnifiedMarketDataEngine
class Tests(unittest.TestCase):
 def setUp(self): self.e=UnifiedMarketDataEngine()
 def test_bybit_snapshot_delta(self):
  s={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","2"]],"a":[["101","3"]],"u":1}}
  self.e.process("bybit",s); self.assertTrue(self.e.get_book("bybit","BTCUSDT")["synchronized"])
  d={"topic":"orderbook.50.BTCUSDT","type":"delta","data":{"s":"BTCUSDT","b":[["100","0"],["99","4"]],"a":[],"u":2}}
  self.e.process("bybit",d); self.assertEqual(self.e.get_book("bybit","BTCUSDT")["best_bid"],99.0)
 def test_trade(self):
  x=self.e.process("bybit",{"topic":"publicTrade.BTCUSDT","data":[{"s":"BTCUSDT","p":"101","v":"2","S":"Buy"}]})
  self.assertEqual(x["side"],"buy")
 def test_binance_diff_unsynced(self):
  x=self.e.process("binance",{"e":"depthUpdate","s":"BTCUSDT","U":1,"u":2,"b":[["10","1"]],"a":[["11","2"]]})
  self.assertFalse(x["synchronized"])
 def test_status_exposes_live_book_diagnostics(self):
  s={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","2"],["99","1"]],"a":[["101","3"],["102","2"]],"u":7}}
  self.e.process("bybit",s)
  status=self.e.get_status()
  book=status["books"]["bybit:BTCUSDT"]
  self.assertTrue(book["synchronized"])
  self.assertEqual(book["sequence"],7)
  self.assertEqual(book["best_bid"],100.0)
  self.assertEqual(book["best_ask"],101.0)
  self.assertEqual(book["spread"],1.0)
  self.assertEqual(book["bid_depth_top10"],3.0)
  self.assertEqual(book["ask_depth_top10"],5.0)
  self.assertAlmostEqual(book["imbalance_top10"],-0.25)
  self.assertIsNotNone(book["age_seconds"])
  self.assertEqual(status["exchanges"]["bybit"]["messages_received"],1)
 def test_status_marks_stale_book(self):
  s={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","1"]],"a":[["101","1"]],"u":1}}
  self.e.process("bybit",s)
  self.e.stale_after_seconds=0
  self.assertTrue(self.e.get_status()["books"]["bybit:BTCUSDT"]["stale"])
 def test_stale(self):
  self.e.process("bybit",{"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["10","1"]],"a":[["11","1"]]}})
  self.e.stale_after_seconds=0; self.assertTrue(self.e.get_book("bybit","BTCUSDT")["stale"])
 def test_binance_unbridged_depth_does_not_mutate_or_refresh_book(self):
  raw={"e":"depthUpdate","s":"BTCUSDT","U":100,"u":101,"b":[["100","1"]],"a":[["101","2"]]}
  with patch("app.market_data.unified_engine.time.time",return_value=10.0):
   result=self.e.process("binance",raw)
  book=self.e.get_book("binance","BTCUSDT")
  status=self.e.get_status()
  self.assertEqual(result,{"type":"book_delta","synchronized":False})
  self.assertFalse(book["synchronized"])
  self.assertTrue(book["stale"])
  self.assertEqual(book["bids"],[])
  self.assertEqual(book["asks"],[])
  self.assertIsNone(book["sequence"])
  self.assertIsNone(book["received_timestamp_ms"])
  self.assertEqual(status["exchanges"]["binance"]["messages_received"],1)
 def test_binance_trade_does_not_refresh_book_freshness(self):
  book=self.e.book("binance","BTCUSDT")
  book.bids={100.0:1.0}; book.asks={101.0:1.0}
  book.synchronized=True; book.received_ts=100000; book.exchange_ts=100000
  raw={"e":"aggTrade","s":"BTCUSDT","p":"101","q":"2","m":False,"T":200000}
  with patch("app.market_data.unified_engine.time.time",return_value=200.0):
   result=self.e.process("binance",raw)
  with patch("app.market_data.unified_engine.time.time",return_value=201.0):
   current=self.e.get_book("binance","BTCUSDT")
   status=self.e.get_status()
  self.assertEqual(result["type"],"trade")
  self.assertEqual(current["received_timestamp_ms"],100000)
  self.assertEqual(current["age_seconds"],101.0)
  self.assertTrue(current["stale"])
  self.assertEqual(status["exchanges"]["binance"]["messages_received"],1)
  self.assertEqual(status["exchanges"]["binance"]["last_message_age_seconds"],1.0)
if __name__=="__main__":unittest.main()
