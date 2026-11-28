import unittest
from unittest.mock import patch
from app.market_data.unified_engine import UnifiedMarketDataEngine
class Tests(unittest.TestCase):
 def setUp(self): self.e=UnifiedMarketDataEngine()
 def test_unified_stale_cutoff_invalid_values_fall_back_to_default(self):
  for invalid in (None, "", "invalid", float("nan"), float("inf"), float("-inf"), 0, -1, True, False):
   with self.subTest(value=invalid):
    self.assertEqual(UnifiedMarketDataEngine(stale_after_seconds=invalid).stale_after_seconds, 3.0)
 def test_unified_stale_cutoff_preserves_valid_values_and_clamps_minimum(self):
  self.assertEqual(UnifiedMarketDataEngine(stale_after_seconds=1.25).stale_after_seconds, 1.25)
  self.assertEqual(UnifiedMarketDataEngine(stale_after_seconds="2.5").stale_after_seconds, 2.5)
  self.assertEqual(UnifiedMarketDataEngine(stale_after_seconds=0.05).stale_after_seconds, 0.1)
 def test_bybit_snapshot_delta(self):
  s={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","2"]],"a":[["101","3"]],"u":1}}
  self.e.process("bybit",s); self.assertTrue(self.e.get_book("bybit","BTCUSDT")["synchronized"])
  d={"topic":"orderbook.50.BTCUSDT","type":"delta","data":{"s":"BTCUSDT","b":[["100","0"],["99","4"]],"a":[],"u":2}}
  self.e.process("bybit",d); self.assertEqual(self.e.get_book("bybit","BTCUSDT")["best_bid"],99.0)
 def test_trade(self):
  x=self.e.process("bybit",{"topic":"publicTrade.BTCUSDT","data":[{"s":"BTCUSDT","p":"101","v":"2","S":"Buy"}]})
  self.assertEqual(x["side"],"buy")

 def test_public_trade_topic_resolves_missing_payload_symbol(self):
  message={"topic":"publicTrade.ETHUSDT","data":{"p":"2020","v":"1","S":"Sell"}}
  with patch("app.market_data.unified_engine.time.time",return_value=100.0):
   result=self.e.process("bybit",message)
  self.assertEqual(result["symbol"],"ETHUSDT")
  status=self.e.get_status()
  self.assertEqual(status["feeds"]["bybit:ETHUSDT"]["messages_received"],1)
  self.assertNotIn("bybit:BTCUSDT",status["feeds"])
  self.assertEqual(status["invalid_symbol_message_count"],0)

 def test_topic_and_payload_symbol_conflict_is_rejected_and_counted(self):
  message={"topic":"publicTrade.BTCUSDT","data":{"s":"ETHUSDT","p":"2020","v":"1","S":"Sell"}}
  result=self.e.process("bybit",message)
  status=self.e.get_status()
  self.assertIsNone(result)
  self.assertEqual(status["invalid_symbol_message_count"],1)
  self.assertEqual(status["feeds"],{})
  self.assertEqual(status["trade_streams"],{})

 def test_malformed_explicit_symbol_is_rejected_and_counted(self):
  message={"topic":"publicTrade.BTCUSDT","data":{"s":123,"p":"2020","v":"1","S":"Sell"}}
  result=self.e.process("bybit",message)
  status=self.e.get_status()
  self.assertIsNone(result)
  self.assertEqual(status["invalid_symbol_message_count"],1)
  self.assertEqual(status["feeds"],{})

 def test_orderbook_topic_resolves_missing_payload_symbol(self):
  snapshot={"topic":"orderbook.50.ETHUSDT","type":"snapshot","data":{"b":[["2000","2"]],"a":[["2001","3"]],"u":1}}
  result=self.e.process("bybit",snapshot)
  book=self.e.get_book("bybit","ETHUSDT")
  self.assertTrue(book["synchronized"])
  self.assertEqual(book["best_bid"],2000.0)
  self.assertEqual(result["type"],"book_snapshot")
  self.assertEqual(self.e.get_status()["invalid_symbol_message_count"],0)

 def test_single_symbol_default_fallback_is_retained(self):
  message={"e":"aggTrade","p":"101","q":"2","m":False}
  result=self.e.process("binance",message,default_symbol="BTCUSDT")
  self.assertEqual(result["symbol"],"BTCUSDT")
  self.assertEqual(self.e.get_status()["feeds"]["binance:BTCUSDT"]["messages_received"],1)
  self.assertEqual(self.e.get_status()["invalid_symbol_message_count"],0)
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
  self.assertEqual(status["feeds"]["bybit:BTCUSDT"]["messages_received"],1)
  self.assertIsNotNone(status["feeds"]["bybit:BTCUSDT"]["last_message_age_seconds"])
 def test_status_tracks_message_freshness_per_symbol(self):
  btc={"topic":"publicTrade.BTCUSDT","data":{"s":"BTCUSDT","p":"101","v":"2","S":"Buy"}}
  eth={"topic":"publicTrade.ETHUSDT","data":{"s":"ETHUSDT","p":"2020","v":"1","S":"Sell"}}
  with patch("app.market_data.unified_engine.time.time",return_value=100.0):
   self.e.process("bybit",btc)
  with patch("app.market_data.unified_engine.time.time",return_value=200.0):
   self.e.process("bybit",eth)
  with patch("app.market_data.unified_engine.time.time",return_value=201.0):
   status=self.e.get_status()
  self.assertEqual(status["feeds"]["bybit:BTCUSDT"]["messages_received"],1)
  self.assertEqual(status["feeds"]["bybit:BTCUSDT"]["last_message_age_seconds"],101.0)
  self.assertEqual(status["feeds"]["bybit:ETHUSDT"]["messages_received"],1)
  self.assertEqual(status["feeds"]["bybit:ETHUSDT"]["last_message_age_seconds"],1.0)
  self.assertEqual(status["exchanges"]["bybit"]["messages_received"],2)
  self.assertEqual(status["exchanges"]["bybit"]["last_message_age_seconds"],1.0)

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

 def test_malformed_trade_does_not_invalidate_or_refresh_book(self):
  snapshot={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","2"]],"a":[["101","3"]],"u":1}}
  with patch("app.market_data.unified_engine.time.time",return_value=100.0):
   self.e.process("bybit",snapshot)
  malformed={"topic":"publicTrade.BTCUSDT","data":{"s":"BTCUSDT","p":"not-a-price","v":"1","S":"Buy"}}
  with patch("app.market_data.unified_engine.time.time",return_value=200.0):
   result=self.e.process("bybit",malformed)
  with patch("app.market_data.unified_engine.time.time",return_value=201.0):
   book=self.e.get_book("bybit","BTCUSDT")
  self.assertIsNone(result)
  self.assertTrue(book["synchronized"])
  self.assertIsNone(book["integrity_error"])
  self.assertEqual(book["received_timestamp_ms"],100000)

 def test_snapshot_retains_only_configured_best_levels(self):
  e=UnifiedMarketDataEngine(max_levels=2)
  s={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","1"],["99","1"],["98","1"]],"a":[["101","1"],["102","1"],["103","1"]],"u":1}}
  e.process("bybit",s)
  book=e.get_book("bybit","BTCUSDT")
  self.assertEqual(book["bids"],[[100.0,1.0],[99.0,1.0]])
  self.assertEqual(book["asks"],[[101.0,1.0],[102.0,1.0]])
  self.assertEqual(len(e.books["bybit:BTCUSDT"].bids),2)
  self.assertEqual(len(e.books["bybit:BTCUSDT"].asks),2)

 def test_delta_trims_depth_but_preserves_best_prices(self):
  e=UnifiedMarketDataEngine(max_levels=2)
  s={"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["100","1"],["99","1"],["98","1"]],"a":[["101","1"],["102","1"],["103","1"]],"u":1}}
  e.process("bybit",s)
  d={"topic":"orderbook.50.BTCUSDT","type":"delta","data":{"s":"BTCUSDT","b":[["99.5","2"]],"a":[["102.5","2"]],"u":2}}
  e.process("bybit",d)
  book=e.get_book("bybit","BTCUSDT")
  self.assertEqual(book["bids"],[[100.0,1.0],[99.5,2.0]])
  self.assertEqual(book["asks"],[[101.0,1.0],[102.0,1.0]])
  self.assertEqual(book["best_bid"],100.0)
  self.assertEqual(book["best_ask"],101.0)
  self.assertEqual(len(e.books["bybit:BTCUSDT"].bids),2)
  self.assertEqual(len(e.books["bybit:BTCUSDT"].asks),2)

 def test_max_levels_must_be_positive_integer(self):
  for invalid in (0,-1,1.5,True,"2"):
   with self.assertRaises(ValueError):
    UnifiedMarketDataEngine(max_levels=invalid)


if __name__=="__main__":unittest.main()
