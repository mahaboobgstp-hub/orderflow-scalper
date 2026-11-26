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
 def test_trade_messages_do_not_refresh_book_freshness(self):
  snapshot={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","2"]],"a":[["101","3"]],"u":7}}
  with patch("app.market_data.unified_engine.time.time",return_value=100.0):
   self.e.process("bybit",snapshot)
  trade={"topic":"publicTrade.BTCUSDT","data":{"s":"BTCUSDT","p":"101","v":"2","S":"Buy"}}
  with patch("app.market_data.unified_engine.time.time",return_value=200.0):
   result=self.e.process("bybit",trade)
  self.assertEqual(result["type"],"trade")
  with patch("app.market_data.unified_engine.time.time",return_value=201.0):
   book=self.e.get_book("bybit","BTCUSDT")
   status=self.e.get_status()
  self.assertTrue(book["stale"])
  self.assertEqual(book["age_seconds"],101.0)
  self.assertEqual(status["exchanges"]["bybit"]["messages_received"],2)
  self.assertEqual(status["exchanges"]["bybit"]["last_message_age_seconds"],1.0)
 def test_invalid_snapshot_preserves_prior_book_and_invalidates(self):
  good={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","2"]],"a":[["101","3"]],"u":1}}
  with patch("app.market_data.unified_engine.time.time",return_value=100.0):
   self.e.process("bybit",good)
  crossed={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["102","1"]],"a":[["101","1"]],"u":2}}
  with patch("app.market_data.unified_engine.time.time",return_value=200.0):
   result=self.e.process("bybit",crossed)
  with patch("app.market_data.unified_engine.time.time",return_value=201.0):
   book=self.e.get_book("bybit","BTCUSDT")
  self.assertFalse(book["synchronized"])
  self.assertTrue(book["stale"])
  self.assertEqual(book["bids"],[[100.0,2.0]])
  self.assertEqual(book["asks"],[[101.0,3.0]])
  self.assertEqual(book["sequence"],1)
  self.assertEqual(book["received_timestamp_ms"],100000)
  self.assertEqual(result["error"],"Crossed or locked order book")

 def test_malformed_delta_is_atomic_and_does_not_refresh(self):
  good={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","2"]],"a":[["101","3"]],"u":1}}
  with patch("app.market_data.unified_engine.time.time",return_value=100.0):
   self.e.process("bybit",good)
  bad={"topic":"orderbook.50.BTCUSDT","type":"delta","data":{"s":"BTCUSDT","b":[["99","4"]],"a":[["101","NaN"]],"u":2}}
  with patch("app.market_data.unified_engine.time.time",return_value=200.0):
   result=self.e.process("bybit",bad)
  with patch("app.market_data.unified_engine.time.time",return_value=201.0):
   book=self.e.get_book("bybit","BTCUSDT")
  self.assertFalse(book["synchronized"])
  self.assertTrue(book["stale"])
  self.assertEqual(book["bids"],[[100.0,2.0]])
  self.assertEqual(book["asks"],[[101.0,3.0]])
  self.assertEqual(book["sequence"],1)
  self.assertEqual(book["received_timestamp_ms"],100000)
  self.assertEqual(result["error"],"Malformed depth levels")

 def test_crossed_delta_is_rejected_without_partial_mutation(self):
  good={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","2"]],"a":[["101","3"]],"u":1}}
  with patch("app.market_data.unified_engine.time.time",return_value=100.0):
   self.e.process("bybit",good)
  crossed={"topic":"orderbook.50.BTCUSDT","type":"delta","data":{"s":"BTCUSDT","b":[["102","1"]],"a":[],"u":2}}
  with patch("app.market_data.unified_engine.time.time",return_value=200.0):
   result=self.e.process("bybit",crossed)
  with patch("app.market_data.unified_engine.time.time",return_value=201.0):
   book=self.e.get_book("bybit","BTCUSDT")
  self.assertFalse(book["synchronized"])
  self.assertEqual(book["bids"],[[100.0,2.0]])
  self.assertEqual(book["asks"],[[101.0,3.0]])
  self.assertEqual(book["sequence"],1)
  self.assertEqual(book["received_timestamp_ms"],100000)
  self.assertEqual(result["error"],"Crossed or locked order book")

 def test_nonprogressing_bybit_sequence_cannot_refresh_book(self):
  good={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","2"]],"a":[["101","3"]],"u":5}}
  with patch("app.market_data.unified_engine.time.time",return_value=100.0):
   self.e.process("bybit",good)
  duplicate={"topic":"orderbook.50.BTCUSDT","type":"delta","data":{"s":"BTCUSDT","b":[["99","1"]],"a":[],"u":5}}
  with patch("app.market_data.unified_engine.time.time",return_value=200.0):
   result=self.e.process("bybit",duplicate)
  with patch("app.market_data.unified_engine.time.time",return_value=201.0):
   book=self.e.get_book("bybit","BTCUSDT")
  self.assertFalse(book["synchronized"])
  self.assertTrue(book["stale"])
  self.assertEqual(book["bids"],[[100.0,2.0]])
  self.assertEqual(book["sequence"],5)
  self.assertEqual(book["received_timestamp_ms"],100000)
  self.assertEqual(result["error"],"Non-progressing order-book sequence")

 def test_delta_before_snapshot_does_not_create_fresh_book(self):
  delta={"topic":"orderbook.50.BTCUSDT","type":"delta","data":{"s":"BTCUSDT","b":[["100","1"]],"a":[["101","1"]],"u":1}}
  with patch("app.market_data.unified_engine.time.time",return_value=200.0):
   result=self.e.process("bybit",delta)
  book=self.e.get_book("bybit","BTCUSDT")
  self.assertFalse(book["synchronized"])
  self.assertTrue(book["stale"])
  self.assertIsNone(book["received_timestamp_ms"])
  self.assertEqual(result["error"],"Delta received before synchronized snapshot")

 def test_nonfinite_trade_price_or_quantity_is_rejected(self):
  for price,quantity in (("NaN","1"),("Infinity","1"),("1","NaN"),("1","Infinity")):
   x=self.e.process("bybit",{"topic":"publicTrade.BTCUSDT","data":{"s":"BTCUSDT","p":price,"v":quantity,"S":"Buy"}})
   self.assertIsNone(x)
  self.assertEqual(self.e.get_recent_trades("bybit","BTCUSDT"),[])

if __name__=="__main__":unittest.main()
