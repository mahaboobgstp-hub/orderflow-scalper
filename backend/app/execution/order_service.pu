from app.config import settings
from app.execution.binance_demo_client import BinanceDemoClient


class OrderRejected(ValueError):
    pass


class DemoOrderService:
    def __init__(self):
        self.client = BinanceDemoClient()

    async def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict:
        if not settings.execution_enabled:
            raise OrderRejected(
                "Demo execution is disabled. Set DEMO_EXECUTION_ENABLED=true "
                "on the backend to allow demo orders."
            )

        symbol = symbol.upper().strip()
        side = side.upper().strip()

        if side not in {"BUY", "SELL"}:
            raise OrderRejected("side must be BUY or SELL.")

        if quantity <= 0:
            raise OrderRejected("quantity must be greater than zero.")

        if quantity > settings.max_order_quantity:
            raise OrderRejected(
                f"quantity exceeds configured maximum "
                f"({settings.max_order_quantity})."
            )

        if not symbol.isalnum():
            raise OrderRejected("Invalid symbol.")

        return await self.client.place_market_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
        )
