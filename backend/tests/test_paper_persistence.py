import unittest
from unittest.mock import AsyncMock
from app.services.paper_persistence import PaperPersistenceWorker

class FakeDB:
    update = AsyncMock(return_value=None)

class FakeRepo:
    def __init__(self):
        self.db=FakeDB()
        self.order=AsyncMock(return_value=[{"id":"order-db-id"}])
        self.position=AsyncMock(return_value=[{"id":"position-db-id"}])
        self.closed_trade=AsyncMock(return_value=[{"id":"trade-db-id"}])
        self.system_log=AsyncMock(return_value=True)
        self.risk_event=AsyncMock(return_value=True)

class PaperPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_event_persists_order_and_position(self):
        repo=FakeRepo()
        worker=PaperPersistenceWorker(repo)
        order={"order_id":"ord-1","symbol":"BTCUSDT","side":"long","quantity":0.01,
               "entry_price":100.0,"status":"FILLED_SIMULATED"}
        position={"position_id":"pos-1","symbol":"BTCUSDT","side":"long","quantity":0.01,
                 "entry_price":100.0,"stop_loss_price":95.0,"take_profit_price":110.0}
        await worker._persist({"type":"order_open","order":order,"position":position})
        repo.order.assert_awaited_once()
        repo.position.assert_awaited_once()
        self.assertEqual(worker.position_ids["BTCUSDT"],"position-db-id")

    async def test_mark_event_updates_open_position(self):
        repo=FakeRepo()
        worker=PaperPersistenceWorker(repo)
        pos={"symbol":"ETHUSDT","tsl_price":95.0,"ttp_price":None}
        await worker._persist({"type":"position_mark","position":pos,"price":100.0})
        repo.db.update.assert_awaited_once()
        self.assertEqual(repo.db.update.await_args.kwargs["filters"]["status"],"eq.OPEN")

    async def test_management_event_updates_and_logs_risk(self):
        repo=FakeRepo()
        worker=PaperPersistenceWorker(repo)
        pos={"symbol":"SOLUSDT","stop_loss_price":90.0,"take_profit_price":120.0}
        await worker._persist({"type":"management_update","position":pos})
        repo.db.update.assert_awaited_once()
        repo.risk_event.assert_awaited_once()

    async def test_close_event_updates_position_and_writes_trade_history(self):
        repo=FakeRepo()
        worker=PaperPersistenceWorker(repo)
        trade={"symbol":"BTCUSDT","side":"long","quantity":0.01,"entry_price":100.0,
                "exit_price":108.0,"net_pnl":0.07,"entry_fee":0.01,"exit_fee":0.02,
                "close_reason":"MANUAL_SIMULATED"}
        await worker._persist({"type":"position_close","trade":trade,"closed_at":"2026-01-01T00:00:00Z"})
        repo.db.update.assert_awaited_once()
        repo.closed_trade.assert_awaited_once()
        self.assertEqual(repo.closed_trade.await_args.kwargs["realized_pnl"],0.07)

if __name__=="__main__":
    unittest.main()

class PaperStateRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_restore_valid_paper_snapshot(self):
        from app.services.paper_trading import PaperTradingEngine
        engine=PaperTradingEngine(initial_equity=2500)
        engine.cash=2100.0
        engine.positions={"BTCUSDT":{"position_id":"p-1","symbol":"BTCUSDT","side":"long","quantity":0.01,"entry_price":100,"margin":100,"leverage":1}}
        engine.mark_prices={"BTCUSDT":105}
        snapshot=engine.persistence_snapshot()
        fresh=PaperTradingEngine(initial_equity=10000)
        self.assertTrue(fresh.restore_persistence_snapshot(snapshot))
        self.assertEqual(fresh.cash,2100.0)
        self.assertEqual(fresh.positions["BTCUSDT"]["position_id"],"p-1")
        self.assertEqual(fresh.mark_prices["BTCUSDT"],105)

    async def test_reject_snapshot_with_wrong_mode_or_invalid_position(self):
        from app.services.paper_trading import PaperTradingEngine
        fresh=PaperTradingEngine()
        self.assertFalse(fresh.restore_persistence_snapshot({"version":1,"mode":"LIVE"}))
        invalid={"version":1,"mode":"PAPER_ONLY","initial_equity":1000,"cash":900,"fee_rate":0.0004,"positions":{"BAD":{"symbol":"BAD","side":"long","quantity":1,"entry_price":10}}}
        self.assertFalse(fresh.restore_persistence_snapshot(invalid))
