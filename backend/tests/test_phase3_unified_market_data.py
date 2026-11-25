import unittest
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
 def test_stale(self):
  self.e.process("bybit",{"topic":"orderbook.50.BTCUSDT","type":"snapshot","data":{"s":"BTCUSDT","b":[["10","1"]],"a":[["11","1"]]}})
  self.e.stale_after_seconds=0; self.assertTrue(self.e.get_book("bybit","BTCUSDT")["stale"])
if __name__=="__main__":unittest.main()
