from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace
import pytest

from app.tradebridge.risk import (
    AccountRisk, MarketQuote, SymbolRules, TradeBridgeRiskError,
    validate_preview_risk,
)

NOW = datetime(2026, 11, 28, 15, 0, tzinfo=timezone.utc)


class Config:
    max_order_quantity = D("0.001")
    max_order_notional_usdt = D("25")
    max_leverage = 3
    max_open_positions = 1

    def validate(self):
        return None


def preview(**kw):
    base = dict(symbol="ETHUSDT", direction="LONG", quantity=D("0.001"),
                entry_reference=D("10000"), stop_loss_price=D("9990"),
                take_profit_price=D("10100"), leverage=2,
                max_slippage_bps=50)
    base.update(kw)
    return SimpleNamespace(**base)


def quote(**kw):
    base = dict(symbol="ETHUSDT", mark_price=D("10000"), bid_price=D("9999"),
                ask_price=D("10001"), updated_at=NOW)
    base.update(kw)
    return MarketQuote(**base)


def rules(**kw):
    base = dict(symbol="ETHUSDT", min_quantity=D("0.001"), max_quantity=D("10"),
                step_size=D("0.001"), min_notional_usdt=D("5"), tick_size=D("0.1"),
                updated_at=NOW)
    base.update(kw)
    return SymbolRules(**base)


def account(**kw):
    base = dict(equity_usdt=D("1000"), available_margin_usdt=D("100"),
                open_positions_count=0, current_open_risk_usdt=D("0"),
                updated_at=NOW)
    base.update(kw)
    return AccountRisk(**base)


def valid(**kw):
    return validate_preview_risk(preview(), quote(), rules(), account(), Config(), now=NOW, **kw)


def test_valid_preview_returns_server_calculated_limits():
    result=valid()
    assert result.notional_usdt == D("10")
    assert result.required_margin_usdt == D("5")
    assert result.stop_risk_usdt == D("0.01")
    assert result.spread_bps == D("2")
    assert result.quote_age_seconds == 0
    assert result.account_age_seconds == 0
    assert result.exchange_rules_age_seconds == 0


def test_stale_quote_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Market quote data is stale"):
        validate_preview_risk(preview(), quote(updated_at=NOW-timedelta(seconds=3)), rules(), account(), Config(), now=NOW)


def test_future_quote_beyond_clock_skew_rejected():
    with pytest.raises(TradeBridgeRiskError, match="future"):
        validate_preview_risk(preview(), quote(updated_at=NOW+timedelta(seconds=2)), rules(), account(), Config(), now=NOW)


def test_quote_must_match_symbol():
    with pytest.raises(TradeBridgeRiskError, match="symbol must match"):
        validate_preview_risk(preview(), quote(symbol="BTCUSDT"), rules(), account(), Config(), now=NOW)


def test_crossed_or_nonpositive_quote_rejected():
    with pytest.raises(TradeBridgeRiskError, match="invalid or crossed"):
        validate_preview_risk(preview(), quote(bid_price=D("10002"), ask_price=D("10001")), rules(), account(), Config(), now=NOW)


def test_wide_spread_rejected():
    with pytest.raises(TradeBridgeRiskError, match="spread"):
        validate_preview_risk(preview(), quote(bid_price=D("9900"), ask_price=D("10100")), rules(), account(), Config(), now=NOW)


def test_quantity_step_mismatch_rejected():
    with pytest.raises(TradeBridgeRiskError, match="quantity filters"):
        validate_preview_risk(preview(quantity=D("0.0015")), quote(), rules(), account(), SimpleNamespace(max_order_quantity=D("0.01"), max_order_notional_usdt=D("25"), max_leverage=3, max_open_positions=1, validate=lambda: None), now=NOW)


def test_quantity_above_config_cap_rejected():
    with pytest.raises(TradeBridgeRiskError, match="configured safety bounds"):
        cfg=SimpleNamespace(max_order_quantity=D("0.0005"), max_order_notional_usdt=D("25"), max_leverage=3, max_open_positions=1, validate=lambda: None)
        validate_preview_risk(preview(), quote(), rules(), account(), cfg, now=NOW)


def test_minimum_notional_rejected():
    with pytest.raises(TradeBridgeRiskError, match="below the exchange minimum"):
        validate_preview_risk(preview(), quote(), rules(min_notional_usdt=D("50")), account(), Config(), now=NOW)


def test_max_notional_rejected():
    with pytest.raises(TradeBridgeRiskError, match="configured safety cap"):
        validate_preview_risk(preview(quantity=D("0.003")), quote(), rules(), account(), SimpleNamespace(max_order_quantity=D("0.01"), max_order_notional_usdt=D("25"), max_leverage=3, max_open_positions=1, validate=lambda: None), now=NOW)


def test_tick_size_mismatch_rejected():
    with pytest.raises(TradeBridgeRiskError, match="tick-size"):
        validate_preview_risk(preview(stop_loss_price=D("9990.05")), quote(), rules(tick_size=D("0.1")), account(), Config(), now=NOW)


def test_entry_slippage_from_mark_rejected():
    with pytest.raises(TradeBridgeRiskError, match="slippage bound"):
        validate_preview_risk(preview(entry_reference=D("10060")), quote(), rules(), account(), Config(), now=NOW)


def test_long_stop_must_be_below_current_mark():
    with pytest.raises(TradeBridgeRiskError, match="Long stop"):
        validate_preview_risk(preview(stop_loss_price=D("10000")), quote(), rules(), account(), Config(), now=NOW)


def test_short_stop_and_take_profit_geometry():
    p=preview(direction="SHORT", stop_loss_price=D("10010"), take_profit_price=D("9900"))
    assert validate_preview_risk(p, quote(), rules(), account(), Config(), now=NOW).direction == "SHORT"
    with pytest.raises(TradeBridgeRiskError, match="Short stop"):
        validate_preview_risk(preview(direction="SHORT", stop_loss_price=D("9990"), take_profit_price=D("9900")), quote(), rules(), account(), Config(), now=NOW)


def test_leverage_above_configured_cap_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Leverage"):
        validate_preview_risk(preview(leverage=4), quote(), rules(), account(), Config(), now=NOW)


def test_open_position_cap_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Maximum open-position"):
        validate_preview_risk(preview(), quote(), rules(), account(open_positions_count=1), Config(), now=NOW)


def test_margin_shortfall_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Insufficient available margin"):
        validate_preview_risk(preview(), quote(), rules(), account(available_margin_usdt=D("4")), Config(), now=NOW)


def test_per_trade_risk_limit_rejected():
    p=preview(stop_loss_price=D("0.1"))
    with pytest.raises(TradeBridgeRiskError, match="per-trade risk cap"):
        validate_preview_risk(p, quote(), rules(), account(equity_usdt=D("500")), Config(), now=NOW)


def test_total_portfolio_risk_limit_rejected():
    with pytest.raises(TradeBridgeRiskError, match="portfolio risk cap"):
        validate_preview_risk(preview(), quote(), rules(), account(current_open_risk_usdt=D("20")), Config(), now=NOW)


def test_naive_quote_time_rejected():
    with pytest.raises(TradeBridgeRiskError, match="timezone-aware"):
        validate_preview_risk(preview(), quote(updated_at=datetime(2026,11,28,15,0)), rules(), account(), Config(), now=NOW)


def test_nan_market_price_rejected():
    with pytest.raises(TradeBridgeRiskError, match="finite"):
        validate_preview_risk(preview(), quote(mark_price=D("NaN")), rules(), account(), Config(), now=NOW)


def test_invalid_exchange_rules_rejected():
    with pytest.raises(TradeBridgeRiskError, match="quantity rules"):
        validate_preview_risk(preview(), quote(), rules(step_size=D("0")), account(), Config(), now=NOW)


def test_stale_account_snapshot_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Account risk snapshot data is stale"):
        validate_preview_risk(preview(), quote(), rules(), account(updated_at=NOW-timedelta(seconds=6)), Config(), now=NOW)


def test_stale_exchange_rules_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Exchange rules data is stale"):
        validate_preview_risk(preview(), quote(), rules(updated_at=NOW-timedelta(hours=2)), account(), Config(), now=NOW)


def test_existing_portfolio_over_risk_limit_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Existing portfolio risk"):
        validate_preview_risk(preview(), quote(), rules(), account(current_open_risk_usdt=D("21")), Config(), now=NOW)


def test_available_margin_cannot_exceed_equity():
    with pytest.raises(TradeBridgeRiskError, match="Account risk snapshot is invalid"):
        validate_preview_risk(preview(), quote(), rules(), account(available_margin_usdt=D("1001")), Config(), now=NOW)
