"""Fail-closed, server-side TradeBridge market and account risk validation.

This module is side-effect free: it never places orders, calls an exchange, reads
credentials, or enables execution. It validates a proposed preview against trusted
server-supplied quote, exchange rules, account risk, and configuration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_QUOTE_AGE_SECONDS = Decimal("2")
MAX_ACCOUNT_AGE_SECONDS = Decimal("5")
MAX_RULES_AGE_SECONDS = Decimal("3600")
MAX_FUTURE_CLOCK_SKEW_SECONDS = Decimal("1")
MAX_SPREAD_BPS = Decimal("20")
PER_TRADE_RISK_FRACTION = Decimal("0.01")
TOTAL_RISK_FRACTION = Decimal("0.02")


class TradeBridgeRiskError(ValueError):
    """A preview failed a server-side safety check."""


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    mark_price: Decimal
    bid_price: Decimal
    ask_price: Decimal
    updated_at: datetime


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    min_quantity: Decimal
    max_quantity: Decimal
    step_size: Decimal
    min_notional_usdt: Decimal
    tick_size: Decimal
    updated_at: datetime


@dataclass(frozen=True)
class AccountRisk:
    equity_usdt: Decimal
    available_margin_usdt: Decimal
    open_positions_count: int
    current_open_risk_usdt: Decimal
    updated_at: datetime


@dataclass(frozen=True)
class ValidatedPreview:
    symbol: str
    direction: str
    quantity: Decimal
    mark_price: Decimal
    notional_usdt: Decimal
    required_margin_usdt: Decimal
    stop_risk_usdt: Decimal
    quote_age_seconds: float
    account_age_seconds: float
    exchange_rules_age_seconds: float
    spread_bps: Decimal
    entry_slippage_bps: Decimal


def _decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise TradeBridgeRiskError(f"{name} is invalid.") from None
    if not result.is_finite():
        raise TradeBridgeRiskError(f"{name} must be finite.")
    return result


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise TradeBridgeRiskError(f"{name} must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _age_seconds(now: datetime, timestamp: datetime, label: str, max_age: Decimal) -> float:
    age = (now - timestamp).total_seconds()
    if age < -float(MAX_FUTURE_CLOCK_SKEW_SECONDS):
        raise TradeBridgeRiskError(f"{label} timestamp is in the future.")
    if age > float(max_age):
        raise TradeBridgeRiskError(f"{label} data is stale.")
    return age


def _step_aligned(value: Decimal, step: Decimal) -> bool:
    return step > 0 and value % step == 0


def validate_preview_risk(
    preview: Any,
    quote: MarketQuote,
    rules: SymbolRules,
    account: AccountRisk,
    config: Any,
    *,
    now: datetime | None = None,
) -> ValidatedPreview:
    """Validate against server-supplied market/account data and hard-coded limits.

    The caller must obtain quote, symbol filters, and account figures from the
    backend/exchange integration; never accept these fields from a client request.
    """
    now_utc = _aware(now or datetime.now(timezone.utc), "now")
    quote_age = _age_seconds(
        now_utc, _aware(quote.updated_at, "quote.updated_at"),
        "Market quote", MAX_QUOTE_AGE_SECONDS,
    )
    account_age = _age_seconds(
        now_utc, _aware(account.updated_at, "account.updated_at"),
        "Account risk snapshot", MAX_ACCOUNT_AGE_SECONDS,
    )
    rules_age = _age_seconds(
        now_utc, _aware(rules.updated_at, "exchange_rules.updated_at"),
        "Exchange rules", MAX_RULES_AGE_SECONDS,
    )

    config.validate()
    symbol = str(getattr(preview, "symbol", "")).strip().upper()
    raw_direction = getattr(preview, "direction", "")
    direction = str(getattr(raw_direction, "value", raw_direction)).strip().upper()
    if direction not in {"LONG", "SHORT"}:
        raise TradeBridgeRiskError("Direction must be LONG or SHORT.")
    if symbol != quote.symbol.strip().upper() or symbol != rules.symbol.strip().upper():
        raise TradeBridgeRiskError("Preview, quote, and exchange rules symbol must match.")

    mark = _decimal(quote.mark_price, "mark price")
    bid = _decimal(quote.bid_price, "bid price")
    ask = _decimal(quote.ask_price, "ask price")
    quantity = _decimal(preview.quantity, "quantity")
    entry = _decimal(preview.entry_reference, "entry reference")
    stop = _decimal(preview.stop_loss_price, "stop loss")
    take_profit_raw = getattr(preview, "take_profit_price", None)
    take_profit = None if take_profit_raw is None else _decimal(take_profit_raw, "take profit")
    leverage = int(getattr(preview, "leverage", 1))
    slippage_bound = _decimal(getattr(preview, "max_slippage_bps", 0), "slippage bound")

    if min(mark, bid, ask) <= 0 or bid > ask:
        raise TradeBridgeRiskError("Quote is invalid or crossed.")
    mid = (bid + ask) / Decimal(2)
    spread_bps = (ask - bid) / mid * Decimal(10000)
    if spread_bps > MAX_SPREAD_BPS:
        raise TradeBridgeRiskError("Market spread exceeds the preview safety limit.")

    configured_max_quantity = _decimal(config.max_order_quantity, "configured max quantity")
    if quantity <= 0 or quantity > configured_max_quantity:
        raise TradeBridgeRiskError("Quantity exceeds the configured safety bounds.")
    min_qty = _decimal(rules.min_quantity, "exchange minimum quantity")
    max_qty = _decimal(rules.max_quantity, "exchange maximum quantity")
    step = _decimal(rules.step_size, "exchange quantity step")
    if min_qty <= 0 or max_qty <= 0 or step <= 0 or min_qty > max_qty:
        raise TradeBridgeRiskError("Exchange quantity rules are invalid.")
    if quantity < min_qty or quantity > max_qty or not _step_aligned(quantity, step):
        raise TradeBridgeRiskError("Quantity violates exchange quantity filters.")

    tick = _decimal(rules.tick_size, "exchange tick size")
    order_prices = [stop] + ([take_profit] if take_profit is not None else [])
    if tick <= 0 or not all(_step_aligned(price, tick) for price in order_prices):
        raise TradeBridgeRiskError("Stop/take-profit price violates exchange tick-size rules.")

    notional = quantity * mark
    minimum_notional = _decimal(rules.min_notional_usdt, "exchange minimum notional")
    if minimum_notional < 0:
        raise TradeBridgeRiskError("Exchange minimum notional is invalid.")
    if notional < minimum_notional:
        raise TradeBridgeRiskError("Order notional is below the exchange minimum.")
    if notional > _decimal(config.max_order_notional_usdt, "configured max notional"):
        raise TradeBridgeRiskError("Order notional exceeds the configured safety cap.")
    if leverage < 1 or leverage > int(config.max_leverage):
        raise TradeBridgeRiskError("Leverage exceeds the configured safety cap.")

    entry_slippage = abs(entry - mark) / mark * Decimal(10000)
    if entry_slippage > slippage_bound:
        raise TradeBridgeRiskError("Entry price is outside the approved slippage bound.")

    if direction == "LONG":
        if stop >= mark or (take_profit is not None and take_profit <= mark):
            raise TradeBridgeRiskError("Long stop/take-profit geometry invalid at current mark.")
    elif stop <= mark or (take_profit is not None and take_profit >= mark):
        raise TradeBridgeRiskError("Short stop/take-profit geometry invalid at current mark.")

    equity = _decimal(account.equity_usdt, "account equity")
    available_margin = _decimal(account.available_margin_usdt, "available margin")
    current_risk = _decimal(account.current_open_risk_usdt, "current open risk")
    if equity <= 0 or not 0 <= available_margin <= equity or current_risk < 0:
        raise TradeBridgeRiskError("Account risk snapshot is invalid.")
    if (
        isinstance(account.open_positions_count, bool)
        or not isinstance(account.open_positions_count, int)
        or account.open_positions_count < 0
    ):
        raise TradeBridgeRiskError("Open-position count is invalid.")
    if account.open_positions_count >= int(config.max_open_positions):
        raise TradeBridgeRiskError("Maximum open-position limit reached.")
    if current_risk > equity * TOTAL_RISK_FRACTION:
        raise TradeBridgeRiskError("Existing portfolio risk already exceeds the risk cap.")

    margin = notional / Decimal(leverage)
    if margin > available_margin:
        raise TradeBridgeRiskError("Insufficient available margin for this preview.")
    stop_risk = abs(mark - stop) * quantity
    if stop_risk > equity * PER_TRADE_RISK_FRACTION:
        raise TradeBridgeRiskError("Proposed stop risk exceeds per-trade risk cap.")
    if current_risk + stop_risk > equity * TOTAL_RISK_FRACTION:
        raise TradeBridgeRiskError("Proposed stop risk exceeds portfolio risk cap.")

    return ValidatedPreview(
        symbol=symbol,
        direction=direction,
        quantity=quantity,
        mark_price=mark,
        notional_usdt=notional,
        required_margin_usdt=margin,
        stop_risk_usdt=stop_risk,
        quote_age_seconds=quote_age,
        account_age_seconds=account_age,
        exchange_rules_age_seconds=rules_age,
        spread_bps=spread_bps,
        entry_slippage_bps=entry_slippage,
    )
