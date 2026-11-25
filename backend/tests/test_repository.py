import unittest
from unittest.mock import AsyncMock

from app.database.repository import OrderFlowRepository


class FakeDB:
    def __init__(self):
        self.insert = AsyncMock(return_value=[{"id": "test-id"}])
        self.select = AsyncMock(return_value=[])
        self.update = AsyncMock(return_value=None)


class RepositoryContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_log_uses_schema_fields(self):
        db = FakeDB()
        repo = OrderFlowRepository(db)
        ok = await repo.system_log("warning", "test", "test-component", {"k": "v"})
        self.assertTrue(ok)
        db.insert.assert_awaited_once()
        table, payload = db.insert.await_args.args
        self.assertEqual(table, "system_logs")
        self.assertEqual(payload["level"], "WARNING")
        self.assertEqual(payload["message"], "test")

    async def test_engine_state_inserts_when_empty(self):
        db = FakeDB()
        repo = OrderFlowRepository(db)
        ok = await repo.engine_state(state={"safe": True})
        self.assertTrue(ok)
        db.insert.assert_awaited_once()
        self.assertEqual(db.insert.await_args.args[0], "engine_state")
        self.assertFalse(db.insert.await_args.args[1]["execution_enabled"])

    async def test_engine_state_updates_existing_row(self):
        db = FakeDB()
        db.select = AsyncMock(return_value=[{"id": "existing"}])
        repo = OrderFlowRepository(db)
        ok = await repo.engine_state(status="paused")
        self.assertTrue(ok)
        db.update.assert_awaited_once()
        self.assertEqual(db.update.await_args.kwargs["filters"], {"id": "eq.existing"})

    async def test_risk_event_reports_write_failure(self):
        db = FakeDB()
        db.insert.side_effect = RuntimeError("database unavailable")
        repo = OrderFlowRepository(db)
        self.assertFalse(await repo.risk_event("test_event"))


if __name__ == "__main__":
    unittest.main()
