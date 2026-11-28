"""Read-only Binance Futures Demo snapshot provider for TradeBridge previews."""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.execution.binance_demo_client import BinanceDemoClient
from .config import TradeBridgeConfig
from .risk import AccountRisk, MarketQuote, SymbolRules


class SnapshotProviderError(ValueError):
    """Raised when trusted preview snapshots cannot be assembled safely."""


def _symbol(value: str) -> str:
    normalized = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,20}USDT", normalized):
        raise SnapshotProviderError("TradeBridge supports USDT perpetual symbols only.")
    return normalized


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise SnapshotProviderError(f"{label} is invalid.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise SnapshotProviderError(f"{label} is invalid.") from None
    if not number.is_finite() or (positive and number <= 0):
        raise SnapshotProviderError(f"{label} is invalid.")
    return number


def _utc_now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise SnapshotProviderError("Snapshot time must be timezone-aware.")
    return value.astimezone(timezone.utc)


def parse_market_quote(
    symbol: str,
    mark_payload: dict[str, Any],
    book_payload: dict[str, Any],
    *,
    now: datetime | None = None,
) -> MarketQuote:
    normalized = _symbol(symbol)
    if not isinstance(mark_payload, dict) or not isinstance(book_payload, dict):
        raise SnapshotProviderError("Market quote response is malformed.")
    for payload in (mark_payload, book_payload):
        if str(payload.get("symbol", "")).strip().upper() != normalized:
            raise SnapshotProviderError("Market quote symbol does not match request.")
    return MarketQuote(
        symbol=normalized,
        mark_price=_decimal(mark_payload.get("markPrice"), "mark price", positive=True),
        bid_price=_decimal(book_payload.get("bidPrice"), "bid price", positive=True),
        ask_price=_decimal(book_payload.get("askPrice"), "ask price", positive=True),
        updated_at=_utc_now(now),
    )


def parse_symbol_rules(
    symbol: str,
    exchange_info: dict[str, Any],
    *,
    now: datetime | None = None,
) -> SymbolRules:
    normalized = _symbol(symbol)
    if not isinstance(exchange_info, dict):
        raise SnapshotProviderError("Exchange symbol metadata is unavailable.")
    rows = exchange_info.get("symbols")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise SnapshotProviderError("Exchange symbol metadata is malformed.")
    item = next((row for row in rows if str(row.get("symbol", "")).upper() == normalized), None)
    if item is None or item.get("status") != "TRADING":
        raise SnapshotProviderError("Symbol is not currently tradable on Demo Futures.")
    if item.get("quoteAsset") != "USDT" or item.get("marginAsset") != "USDT":
        raise SnapshotProviderError("TradeBridge requires USDT-margined contracts.")
    if item.get("contractType") != "PERPETUAL":
        raise SnapshotProviderError("TradeBridge only permits perpetual contracts.")
    raw_filters = item.get("filters")
    if not isinstance(raw_filters, list) or any(not isinstance(row, dict) for row in raw_filters):
        raise SnapshotProviderError("Exchange filters are malformed.")
    filters = {row.get("filterType"): row for row in raw_filters}
    lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE")
    price = filters.get("PRICE_FILTER")
    notional = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL")
    if not lot or not price or not notional:
        raise SnapshotProviderError("Required exchange quantity, price, or notional filter is missing.")
    min_notional_value = notional.get("notional", notional.get("minNotional"))
    min_quantity = _decimal(lot.get("minQty"), "minimum quantity", positive=True)
    max_quantity = _decimal(lot.get("maxQty"), "maximum quantity", positive=True)
    step_size = _decimal(lot.get("stepSize"), "quantity step", positive=True)
    if min_quantity > max_quantity:
        raise SnapshotProviderError("Exchange quantity range is invalid.")
    return SymbolRules(
        symbol=normalized,
        min_quantity=min_quantity,
        max_quantity=max_quantity,
        step_size=step_size,
        min_notional_usdt=_decimal(min_notional_value, "minimum notional", positive=True),
        tick_size=_decimal(price.get("tickSize"), "price tick size", positive=True),
        updated_at=_utc_now(now),
    )


def parse_account_risk(
    account_payload: dict[str, Any],
    open_orders: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> AccountRisk:
    if not isinstance(account_payload, dict):
        raise SnapshotProviderError("Account response is malformed.")
    if not isinstance(open_orders, list) or any(not isinstance(row, dict) for row in open_orders):
        raise SnapshotProviderError("Open-order response is malformed.")
    if open_orders:
        raise SnapshotProviderError("Preview blocked while open orders exist; pending exposure is not reconciled.")
    positions = account_payload.get("positions")
    if not isinstance(positions, list) or not positions or any(not isinstance(row, dict) for row in positions):
        raise SnapshotProviderError("Account positions are unavailable; risk cannot be reconciled.")
    active = []
    for row in positions:
        amount = _decimal(row.get("positionAmt"), "position amount")
        if amount != 0:
            active.append(row)
    if active:
        # Stop orders are not reconciled by this provider. Do not assume open risk is zero.
        raise SnapshotProviderError("Preview blocked while positions exist; protective-stop risk is not reconciled.")
    equity = _decimal(account_payload.get("totalMarginBalance"), "account equity", positive=True)
    available = _decimal(account_payload.get("availableBalance"), "available margin")
    if available < 0 or available > equity:
        raise SnapshotProviderError("Account margin snapshot is inconsistent.")
    return AccountRisk(
        equity_usdt=equity,
        available_margin_usdt=available,
        open_positions_count=0,
        current_open_risk_usdt=Decimal("0"),
        updated_at=_utc_now(now),
    )


class TradeBridgeSnapshotProvider:
    """Fetch trusted, read-only snapshots from the Binance Futures Demo host."""
    def __init__(self, client: BinanceDemoClient | None = None, config: TradeBridgeConfig | None = None):
        self.config = config or TradeBridgeConfig()
        self.client = client or BinanceDemoClient()

    async def fetch(self, symbol: str) -> tuple[MarketQuote, SymbolRules, AccountRisk]:
        normalized = _symbol(symbol)
        if not self.config.enabled:
            raise SnapshotProviderError("TradeBridge is disabled on the backend.")
        self.config.validate()
        client_base = str(getattr(self.client, "base_url", "")).rstrip("/")
        if client_base != self.config.binance_base_url.rstrip("/"):
            raise SnapshotProviderError("Demo client endpoint does not match the validated TradeBridge endpoint.")

        market_started = time.monotonic()
        mark_payload, book_payload, exchange_info = await asyncio.gather(
            self.client.get_mark_price(normalized),
            self.client.get_book_ticker(normalized),
            self.client.get_exchange_info(),
        )
        market_received_at = datetime.now(timezone.utc)
        if time.monotonic() - market_started > 2.0:
            raise SnapshotProviderError("Market snapshot request exceeded the freshness window.")

        account_started = time.monotonic()
        account_payload, open_orders = await asyncio.gather(
            self.client.get_account(),
            self.client.get_open_orders(),
        )
        account_received_at = datetime.now(timezone.utc)
        if time.monotonic() - account_started > 5.0:
            raise SnapshotProviderError("Account snapshot request exceeded the freshness window.")

        quote = parse_market_quote(normalized, mark_payload, book_payload, now=market_received_at)
        rules = parse_symbol_rules(normalized, exchange_info, now=market_received_at)
        account = parse_account_risk(account_payload, open_orders, now=account_received_at)
        return quote, rules, account
