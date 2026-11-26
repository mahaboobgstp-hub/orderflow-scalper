import unittest
from unittest.mock import AsyncMock
from app.services.paper_persistence import PaperPersistenceWorker

class FakeDB:
    def __init__(self):
        self.update = AsyncMock(return_value=None)

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


class PaperPersistenceRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_repository_loads_snapshot_and_open_positions(self):
        from app.database.repository import OrderFlowRepository

        snapshot = {"paper_account": {"mode": "PAPER_ONLY", "cash": 2100.0}}
        open_positions = [{"id": "db-pos-1", "symbol": "BTCUSDT", "status": "OPEN"}]
        db = FakeDBForRepository([[
            {"state_json": snapshot, "updated_at": "2026-11-26T00:00:00Z"}
        ], open_positions])
        repo = OrderFlowRepository(db)

        loaded = await repo.load_paper_state()

        self.assertEqual(loaded["snapshot"], snapshot)
        self.assertEqual(loaded["open_positions"], open_positions)
        self.assertEqual(db.select.await_count, 2)
        self.assertEqual(db.select.await_args_list[0].args[0], "engine_state")
        self.assertEqual(db.select.await_args_list[1].args[0], "positions")
        self.assertEqual(db.select.await_args_list[1].kwargs["filters"], {"status": "eq.OPEN"})

    async def test_repository_save_paper_state_preserves_account_snapshot(self):
        from app.database.repository import OrderFlowRepository

        prior = {"paper_account": {"older": True}, "other_metadata": "keep"}
        snapshot = {"mode": "PAPER_ONLY", "cash": 2200.0}
        db = FakeDBForRepository([[{"id": "state-1", "state_json": prior}]])
        repo = OrderFlowRepository(db)

        saved = await repo.save_paper_state(snapshot)

        self.assertTrue(saved)
        payload = db.update.await_args.args[1]
        self.assertEqual(payload["mode"], "DEMO_PAPER_ONLY")
        self.assertFalse(payload["execution_enabled"])
        self.assertEqual(payload["state_json"]["paper_account"], snapshot)
        self.assertEqual(payload["state_json"]["other_metadata"], "keep")


class FakeDBForRepository:
    def __init__(self, select_results):
        from unittest.mock import AsyncMock
        self.select = AsyncMock(side_effect=select_results)
        self.update = AsyncMock(return_value=None)
        self.insert = AsyncMock(return_value=None)


class PaperPersistenceWorkerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    class RecoveryRepo:
        def __init__(self, saved):
            self.saved = saved

        async def load_paper_state(self):
            return self.saved

    async def test_worker_restores_paper_account_snapshot_and_position_ids(self):
        from app.services.paper_trading import PaperTradingEngine

        source = PaperTradingEngine(initial_equity=2500.0)
        source.cash = 2100.0
        source.positions = {
            "BTCUSDT": {
                "position_id": "p-1", "symbol": "BTCUSDT", "side": "long",
                "quantity": 0.01, "entry_price": 100.0, "margin": 100.0,
            }
        }
        source.mark_prices = {"BTCUSDT": 105.0}
        snapshot = source.persistence_snapshot()
        saved = {
            "snapshot": {"paper_account": snapshot},
            "open_positions": [{"id": "db-pos-1", "symbol": "BTCUSDT"}],
        }
        worker = PaperPersistenceWorker(self.RecoveryRepo(saved))
        fresh = PaperTradingEngine(initial_equity=10000.0)

        restored = await worker.restore_state(fresh)

        self.assertTrue(restored)
        self.assertTrue(worker.recovery_report["snapshot_valid"])
        self.assertEqual(worker.recovery_report["source"], "account_snapshot")
        self.assertEqual(fresh.cash, 2100.0)
        self.assertEqual(fresh.positions["BTCUSDT"]["position_id"], "p-1")
        self.assertEqual(fresh.mark_prices["BTCUSDT"], 105.0)
        self.assertEqual(worker.position_ids["BTCUSDT"], "db-pos-1")

    async def test_worker_falls_back_to_open_position_rows_when_snapshot_missing(self):
        from app.services.paper_trading import PaperTradingEngine

        position = {
            "position_id": "p-fallback", "symbol": "ETHUSDT", "side": "short",
            "quantity": 0.02, "entry_price": 2000.0, "margin": 200.0,
        }
        saved = {
            "snapshot": {},
            "open_positions": [{
                "id": "db-eth-1", "symbol": "ETHUSDT", "mark_price": 1980.0,
                "position_data": position,
            }],
        }
        worker = PaperPersistenceWorker(self.RecoveryRepo(saved))
        fresh = PaperTradingEngine(initial_equity=10000.0)

        restored = await worker.restore_state(fresh)

        self.assertTrue(restored)
        self.assertEqual(worker.recovery_report["source"], "open_position_fallback")
        self.assertEqual(worker.recovery_report["open_position_count"], 1)
        self.assertEqual(fresh.positions["ETHUSDT"]["position_id"], "p-fallback")
        self.assertEqual(fresh.mark_prices["ETHUSDT"], 1980.0)
        self.assertEqual(worker.position_ids["ETHUSDT"], "db-eth-1")
        self.assertTrue(any("incomplete" in warning for warning in worker.recovery_report["warnings"]))

    async def test_worker_starts_fresh_when_database_has_no_recoverable_state(self):
        from app.services.paper_trading import PaperTradingEngine

        worker = PaperPersistenceWorker(self.RecoveryRepo({"snapshot": {}, "open_positions": []}))
        fresh = PaperTradingEngine(initial_equity=10000.0)

        restored = await worker.restore_state(fresh)

        self.assertFalse(restored)
        self.assertEqual(worker.recovery_report["source"], "fresh_account")
        self.assertFalse(fresh.positions)
