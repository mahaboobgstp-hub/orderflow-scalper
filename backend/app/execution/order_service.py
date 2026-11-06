
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
        except (InvalidOperation, TypeError, ValueError):
            raise OrderRejected(f"Invalid {field_name}.")

        if not result.is_finite():
            raise OrderRejected(f"Invalid {field_name}.")

        return result

    async def _validate_exchange_rules(
        self,
        symbol: str,
        quantity: Decimal,
    ) -> None:
        # Fetch exchange trading information
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
                f"{symbol} is not available on Binance Futures Demo."
            )

        # Check whether the symbol is currently tradable
        if symbol_info.get("status") != "TRADING":
            raise OrderRejected(
                f"{symbol} is not currently trading."
            )

        # Check whether market orders are supported
        order_types = symbol_info.get("orderTypes", [])

        if "MARKET" not in order_types:
            raise OrderRejected(
                f"Market orders are not supported for {symbol}."
            )

        filters = {
            item.get("filterType"): item
            for item in symbol_info.get("filters", [])
        }

        # Prefer MARKET_LOT_SIZE for market orders.
        # Fall back to LOT_SIZE if necessary.
        lot_filter = filters.get("MARKET_LOT_SIZE")

        if not lot_filter:
            lot_filter = filters.get("LOT_SIZE")

        if not lot_filter:
            raise OrderRejected(
                f"Quantity rules are unavailable for {symbol}."
            )

        min_qty = self._decimal(
            lot_filter.get("minQty", 0),
            "minimum quantity",
        )

        max_qty = self._decimal(
            lot_filter.get("maxQty", 0),
            "maximum quantity",
        )

        step_size = self._decimal(
            lot_filter.get("stepSize", 0),
            "quantity step size",
        )

        if min_qty > 0 and quantity < min_qty:
            raise OrderRejected(
                f"Quantity is below the exchange minimum "
                f"of {min_qty}."
            )

        if max_qty > 0 and quantity > max_qty:
            raise OrderRejected(
                f"Quantity exceeds the exchange maximum "
                f"of {max_qty}."
            )

        # Check quantity is an exact multiple of step size
        if step_size > 0:
            if quantity % step_size != 0:
                raise OrderRejected(
                    f"Quantity must be a multiple of {step_size}."
                )

        # Check minimum notional when the exchange applies it
        notional_filter = (
            filters.get("MIN_NOTIONAL")
            or filters.get("NOTIONAL")
        )

        if notional_filter:
            if notional_filter.get("filterType") == "MIN_NOTIONAL":
                min_notional = self._decimal(
                    notional_filter.get("notional", 0),
                    "minimum notional",
                )
                applies_to_market = notional_filter.get(
                    "applyToMarket", False
                )
            else:
                min_notional = self._decimal(
                    notional_filter.get("minNotional", 0),
                    "minimum notional",
                )
                applies_to_market = notional_filter.get(
                    "applyMinToMarket", False
                )

            if applies_to_market and min_notional > 0:
                price_data = await self.client.get_symbol_price(symbol)

                market_price = self._decimal(
                    price_data.get("price"),
                    "market price",
                )

                if market_price <= 0:
                    raise OrderRejected(
                        "Unable to validate minimum notional: "
                        "invalid market price."
                    )

                estimated_notional = quantity * market_price

                if estimated_notional < min_notional:
                    raise OrderRejected(
                        f"Estimated order value {estimated_notional} "
                        f"is below the exchange minimum "
                        f"notional of {min_notional}."
                    )

    async def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict:

        # Execution must be explicitly enabled
        if not settings.execution_enabled:
            raise OrderRejected(
                "Demo execution is disabled. "
                "Set DEMO_EXECUTION_ENABLED=true "
                "on the backend to allow demo orders."
            )

        symbol = symbol.upper().strip()
        side = side.upper().strip()

        if side not in {"BUY", "SELL"}:
            raise OrderRejected(
                "side must be BUY or SELL."
            )

        if not symbol or not symbol.isalnum():
            raise OrderRejected("Invalid symbol.")

        quantity_decimal = self._decimal(
            quantity,
            "quantity",
        )

        if quantity_decimal <= 0:
            raise OrderRejected(
                "Quantity must be greater than zero."
            )

        # Apply our own configured maximum quantity
        configured_max = self._decimal(
            settings.max_order_quantity,
            "configured maximum quantity",
        )

        if quantity_decimal > configured_max:
            raise OrderRejected(
                f"Quantity exceeds configured maximum "
                f"({configured_max})."
            )

        # Validate against live exchange trading rules
        await self._validate_exchange_rules(
            symbol,
            quantity_decimal,
        )

        # Submit order only after all validations pass
        return await self.client.place_market_order(
            symbol=symbol,
            side=side,
            quantity=format(quantity_decimal, "f"),
        )
