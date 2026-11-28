import asyncio
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from app.tradebridge.snapshot_provider import (
    SnapshotProviderError,
    TradeBridgeSnapshotProvider,
    parse_account_risk,
    parse_market_quote,
    parse_symbol_rules,
)

NOW = datetime(2026, 11, 28, 16, 0, tzinfo=timezone.utc)
MARK = {"symbol": "ETHUSDT", "markPrice": "10000"}
BOOK = {"symbol": "ETHUSDT", "bidPrice": "9999", "askPrice": "10001"}
INFO = {"symbols": [{
    "symbol": "ETHUSDT", "status": "TRADING", "quoteAsset": "USDT",
    "marginAsset": "USDT", "contractType": "PERPETUAL",
    "filters": [
        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "10", "stepSize": "0.001"},
        {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
        {"filterType": "MIN_NOTIONAL", "notional": "5"},
    ],
}]}
ACCOUNT = {
    "totalMarginBalance": "1000",
    "availableBalance": "100",
    "positions": [{"positionAmt": "0"}],
}


def test_parse_quote_and_timestamp():
    quote = parse_market_quote("ETHUSDT", MARK, BOOK, now=NOW)
    assert quote.mark_price == D("10000")
    assert quote.bid_price == D("9999")
    assert quote.ask_price == D("10001")
    assert quote.updated_at == NOW


def test_quote_symbol_mismatch_rejected():
    with pytest.raises(SnapshotProviderError, match="symbol"):
        parse_market_quote("ETHUSDT", MARK, {**BOOK, "symbol": "BTCUSDT"}, now=NOW)


def test_nonpositive_quote_values_rejected():
    with pytest.raises(SnapshotProviderError, match="invalid"):
        parse_market_quote("ETHUSDT", {**MARK, "markPrice": "0"}, BOOK, now=NOW)


def test_malformed_quote_rejected():
    with pytest.raises(SnapshotProviderError, match="malformed"):
        parse_market_quote("ETHUSDT", None, BOOK, now=NOW)


def test_parse_exchange_rules():
    rules = parse_symbol_rules("ETHUSDT", INFO, now=NOW)
    assert rules.min_quantity == D("0.001")
    assert rules.step_size == D("0.001")
    assert rules.min_notional_usdt == D("5")
    assert rules.tick_size == D("0.1")


def test_non_trading_symbol_rejected():
    with pytest.raises(SnapshotProviderError, match="tradable"):
        parse_symbol_rules("ETHUSDT", {"symbols": [{**INFO["symbols"][0], "status": "BREAK"}]}, now=NOW)


def test_non_usdt_symbol_rejected():
    with pytest.raises(SnapshotProviderError, match="USDT-margined"):
        parse_symbol_rules("ETHUSDT", {"symbols": [{**INFO["symbols"][0], "quoteAsset": "BTC"}]}, now=NOW)


def test_missing_exchange_filter_rejected():
    with pytest.raises(SnapshotProviderError, match="filter is missing"):
        parse_symbol_rules("ETHUSDT", {"symbols": [{**INFO["symbols"][0], "filters": []}]}, now=NOW)


def test_quantity_range_invalid_rejected():
    bad_filters = [
        {"filterType": "MARKET_LOT_SIZE", "minQty": "10", "maxQty": "1", "stepSize": "0.1"},
        {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
        {"filterType": "MIN_NOTIONAL", "notional": "5"},
    ]
    with pytest.raises(SnapshotProviderError, match="quantity range"):
        parse_symbol_rules("ETHUSDT", {"symbols": [{**INFO["symbols"][0], "filters": bad_filters}]}, now=NOW)


def test_parse_account_with_no_positions_and_orders():
    risk = parse_account_risk(ACCOUNT, [], now=NOW)
    assert risk.equity_usdt == D("1000")
    assert risk.available_margin_usdt == D("100")
    assert risk.open_positions_count == 0
    assert risk.current_open_risk_usdt == 0


def test_account_with_positions_rejected_without_stop_reconciliation():
    with pytest.raises(SnapshotProviderError, match="positions exist"):
        parse_account_risk({**ACCOUNT, "positions": [{"positionAmt": "0.01"}]}, [], now=NOW)


def test_account_with_open_orders_rejected():
    with pytest.raises(SnapshotProviderError, match="open orders exist"):
        parse_account_risk(ACCOUNT, [{"orderId": 1}], now=NOW)


def test_account_missing_positions_rejected():
    with pytest.raises(SnapshotProviderError, match="positions are unavailable"):
        parse_account_risk({"totalMarginBalance": "1000", "availableBalance": "100", "positions": []}, [], now=NOW)


def test_margin_over_equity_rejected():
    with pytest.raises(SnapshotProviderError, match="inconsistent"):
        parse_account_risk({**ACCOUNT, "availableBalance": "1001"}, [], now=NOW)


class FakeClient:
    base_url = "https://demo-fapi.binance.com"

    async def get_mark_price(self, symbol):
        return MARK

    async def get_book_ticker(self, symbol):
        return BOOK

    async def get_exchange_info(self):
        return INFO

    async def get_account(self):
        return ACCOUNT

    async def get_open_orders(self):
        return []


class EnabledConfig:
    enabled = True
    binance_base_url = "https://demo-fapi.binance.com"

    def validate(self):
        return None


class DisabledConfig(EnabledConfig):
    enabled = False


class MismatchedEndpointConfig(EnabledConfig):
    binance_base_url = "https://fapi.binance.com"


def test_provider_returns_read_only_demo_snapshots():
    quote, rules, account = asyncio.run(
        TradeBridgeSnapshotProvider(client=FakeClient(), config=EnabledConfig()).fetch("ETHUSDT")
    )
    assert quote.symbol == rules.symbol == "ETHUSDT"
    assert account.open_positions_count == 0


def test_provider_disabled_fails_closed():
    with pytest.raises(SnapshotProviderError, match="disabled"):
        asyncio.run(TradeBridgeSnapshotProvider(client=FakeClient(), config=DisabledConfig()).fetch("ETHUSDT"))


def test_provider_rejects_endpoint_mismatch():
    with pytest.raises(SnapshotProviderError, match="endpoint does not match"):
        asyncio.run(TradeBridgeSnapshotProvider(client=FakeClient(), config=MismatchedEndpointConfig()).fetch("ETHUSDT"))
