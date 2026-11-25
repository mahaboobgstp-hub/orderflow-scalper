import unittest
from app.services.coin_scanner import CoinMarketScanner
class ScannerTests(unittest.TestCase):
 def test_numeric_and_score_helpers(self):
  self.assertEqual(CoinMarketScanner._number("12.5"),12.5)
  self.assertEqual(CoinMarketScanner._number("bad"),0.0)
  self.assertEqual(CoinMarketScanner._clamp(150),100)
  self.assertEqual(CoinMarketScanner._clamp(-2),0)
 def test_scanner_config_bounds(self):
  s=CoinMarketScanner(shortlist_for_activity=999)
  self.assertEqual(s.shortlist_for_activity,50)
  s=CoinMarketScanner(shortlist_for_activity=-1)
  self.assertEqual(s.shortlist_for_activity,0)
if __name__=="__main__": unittest.main()
