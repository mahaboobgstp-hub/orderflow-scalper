"""Phase 2 adapter infrastructure tests using the standard library."""
import asyncio
import unittest

from app.exchanges.public_adapters import (
    BinancePublicAdapter,
    BybitPublicAdapter,
    DeltaPublicAdapter,
    ExchangeConnectionManager,
)


class Phase2AdapterTests(unittest.TestCase):
    def test_adapters_default_disabled_status(self):
        async def run():
            adapters = [
                BinancePublicAdapter(enabled=False),
                BybitPublicAdapter(enabled=False),
                DeltaPublicAdapter(enabled=False, symbol="BTCUSD"),
            ]
            manager = ExchangeConnectionManager(adapters)
            status = await manager.status()
            self.assertEqual(status["phase"], 2)
            self.assertTrue(status["connection_only"])
            self.assertEqual(len(status["exchanges"]), 3)
            for exchange in status["exchanges"]:
                self.assertFalse(exchange["enabled"])
                self.assertFalse(exchange["connected"])
                self.assertEqual(exchange["reconnect_count"], 0)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
