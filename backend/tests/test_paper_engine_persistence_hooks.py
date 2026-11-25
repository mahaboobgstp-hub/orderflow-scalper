import unittest
from app.services import paper_trading

class PaperEnginePersistenceHookTests(unittest.TestCase):
    def setUp(self):
        self.events=[]
        paper_trading.set_persistence_enqueue(self.events.append)
        self.engine=paper_trading.PaperTradingEngine(initial_equity=1000)

    def tearDown(self):
        paper_trading.set_persistence_enqueue(None)

    def test_open_position_emits_order_and_position_event(self):
        result=self.engine.submit({"symbol":"BTCUSDT","side":"long","quantity":0.001,"price":10000})
        self.assertEqual(result["order"]["status"],"FILLED_SIMULATED")
        self.assertEqual(self.events[-1]["type"],"order_open")
        self.assertEqual(self.events[-1]["order"]["symbol"],"BTCUSDT")
        self.assertEqual(self.events[-1]["position"]["position_id"],result["position"]["position_id"])

    def test_mark_updates_persist_event_for_open_position(self):
        self.engine.submit({"symbol":"ETHUSDT","side":"long","quantity":0.01,"price":100})
        self.engine.mark("ETHUSDT",105)
        self.assertEqual(self.events[-1]["type"],"position_mark")
        self.assertEqual(self.events[-1]["price"],105)

    def test_management_change_emits_event(self):
        self.engine.submit({"symbol":"SOLUSDT","side":"long","quantity":0.1,"price":100})
        self.engine.update_management("SOLUSDT",{"stop_loss_price":95})
        self.assertEqual(self.events[-1]["type"],"management_update")
        self.assertEqual(self.events[-1]["position"]["stop_loss_price"],95)

    def test_manual_close_emits_trade_event(self):
        self.engine.submit({"symbol":"XRPUSDT","side":"short","quantity":1,"price":1})
        trade=self.engine.close("XRPUSDT",0.9)
        self.assertEqual(self.events[-1]["type"],"position_close")
        self.assertEqual(self.events[-1]["trade"]["trade_id"],trade["trade_id"])

if __name__=="__main__":
    unittest.main()
