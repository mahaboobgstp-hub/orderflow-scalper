from decimal import Decimal, InvalidOperation

from app.config import settings
from app.execution.binance_demo_client import BinanceDemoClient


class OrderRejected(ValueError):
    pass


class DemoOrderService:
    def __init__(self):
        self.client = BinanceDemoClient()

    @staticmethod
    def _decimal(value, field_name: str) -> Decimal:
        try:
            result = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise OrderRejected(f"{field_name} must be a valid number.")

        if not result.is_finite():
            raise OrderRejected(f"{field_name} must be a finite number.")

        return result

    async def _validate_market_quantity(
        self,
        *,
        symbol: str,
        quantity: Decimal,
    ) -> None:
        exchange_info = await self.client.get_exchange_info()

        symbol_info = next(
            (
                item
                for item in exchange_info.get("symbols", [])
                if item.get("symbol") == symbol
            ),
            None,
        )

        if not symbol_info:
            raise OrderRejected(
                f"{symbol} was not found in Binance Futures exchange information."
            )

        if symbol_info.get("status") != "TRADING":
            raise OrderRejected(f"{symbol} is not currently tradable.")

        if "MARKET" not in symbol_info.get("orderTypes", []):
            raise OrderRejected(
                f"{symbol} does not support market orders."
            )

        filters = {
            item.get("filterType"): item
            for item in symbol_info.get("filters", [])
        }

        # MARKET_LOT_SIZE is the market-order quantity rule.
        # Fall back to LOT_SIZE only if MARKET_LOT_SIZE is absent.
        lot_filter = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE")

        if not lot_filter:
            raise OrderRejected(
                f"Binance did not provide quantity rules for {symbol}."
            )

        min_qty = self._decimal(lot_filter.get("minQty"), "minQty")
        max_qty = self._decimal(lot_filter.get("maxQty"), "maxQty")
        step_size = self._decimal(lot_filter.get("stepSize"), "stepSize")

        if quantity < min_qty:
            raise OrderRejected(
                f"Quantity {quantity} is below {symbol}'s minimum "
                f"market quantity of {min_qty}."
            )

        if quantity > max_qty:
            raise OrderRejected(
                f"Quantity {quantity} exceeds {symbol}'s maximum "
                f"market quantity of {max_qty}."
            )

        if step_size > 0 and quantity % step_size != 0:
            raise OrderRejected(
                f"Quantity {quantity} does not match {symbol}'s "
                f"market quantity step of {step_size}."
            )

        # Check minimum notional using Binance's current ticker price.
        # Binance performs its own final check at order submission.
        notional_filter = filters.get("MIN_NOTIONAL")

        if notional_filter:
            min_notional_value = (
                notional_filter.get("notional")
                or notional_filter.get("minNotional")
            )

            if min_notional_value is not None:
                min_notional = self._decimal(
                    min_notional_value,
                    "minimum notional",
                )

                ticker = await self.client.get_symbol_price(symbol)
                price = self._decimal(ticker.get("price"), "market price")
                estimated_notional = price * quantity

                if estimated_notional < min_notional:
                    raise OrderRejected(
                        f"Estimated order value {estimated_notional:.8f} "
                        f"is below {symbol}'s minimum notional "
                        f"of {min_notional}."
                    )

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

        if not symbol.isalnum():
            raise OrderRejected("Invalid symbol.")

        quantity_decimal = self._decimal(quantity, "quantity")

        if quantity_decimal <= 0:
            raise OrderRejected("Quantity must be greater than zero.")

        max_configured_quantity = self._decimal(
            settings.max_order_quantity,
            "configured maximum quantity",
        )

        if quantity_decimal > max_configured_quantity:
            raise OrderRejected(
                f"Quantity exceeds configured maximum "
                f"({max_configured_quantity})."
            )

        await self._validate_market_quantity(
            symbol=symbol,
            quantity=quantity_decimal,
        )

        return await self.client.place_market_order(
            symbol=symbol,
            side=side,
            quantity=float(quantity_decimal),
        )
