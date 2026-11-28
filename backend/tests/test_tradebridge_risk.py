from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace
import pytest
from app.tradebridge.risk import AccountRisk, MarketQuote, SymbolRules, TradeBridgeRiskError, validate_preview_risk

NOW = datetime(2026, 11, 28, 15, 0, tzinfo=timezone.utc)

class Config:
    max_order_quantity = D("0.001")
    max_order_notional_usdt = D("25")
    max_leverage = 3
    max_open_positions = 1
    def validate(self):
        return None

def preview(**kw):
    data = dict(symbol="ETHUSDT", direction="LONG", quantity=D("0.001"),
                entry_reference=D("10000"), stop_loss_price=D("9990"),
                take_profit_price=D("10100"), leverage=2, max_slippage_bps=50)
    data.update(kw)
    return SimpleNamespace(**data)

def quote(**kw):
    data = dict(symbol="ETHUSDT", mark_price=D("10000"), bid_price=D("9999"),
                ask_price=D("10001"), updated_at=NOW)
    data.update(kw)
    return MarketQuote(**data)

def rules(**kw):
    data = dict(symbol="ETHUSDT", min_quantity=D("0.001"), max_quantity=D("10"),
                step_size=D("0.001"), min_notional_usdt=D("5"), tick_size=D("0.1"),
                updated_at=NOW)
    data.update(kw)
    return SymbolRules(**data)

def account(**kw):
    data = dict(equity_usdt=D("1000"), available_margin_usdt=D("100"),
                open_positions_count=0, current_open_risk_usdt=D("0"), updated_at=NOW)
    data.update(kw)
    return AccountRisk(**data)

def validate(p=None, q=None, r=None, a=None, cfg=None):
    return validate_preview_risk(p or preview(), q or quote(), r or rules(), a or account(), cfg or Config(), now=NOW)

def test_valid_preview_returns_server_calculated_limits():
    result=validate()
    assert result.notional_usdt == D("10")
    assert result.required_margin_usdt == D("5")
    assert result.stop_risk_usdt == D("0.01")
    assert result.spread_bps == D("2")
    assert result.quote_age_seconds == result.account_age_seconds == result.exchange_rules_age_seconds == 0

def test_stale_quote_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Market quote data is stale"):
        validate(q=quote(updated_at=NOW-timedelta(seconds=3)))

def test_future_quote_beyond_clock_skew_rejected():
    with pytest.raises(TradeBridgeRiskError, match="future"):
        validate(q=quote(updated_at=NOW+timedelta(seconds=2)))

def test_quote_must_match_symbol():
    with pytest.raises(TradeBridgeRiskError, match="symbol must match"):
        validate(q=quote(symbol="BTCUSDT"))

def test_crossed_or_nonpositive_quote_rejected():
    with pytest.raises(TradeBridgeRiskError, match="invalid or crossed"):
        validate(q=quote(bid_price=D("10002"), ask_price=D("10001")))

def test_wide_spread_rejected():
    with pytest.raises(TradeBridgeRiskError, match="spread"):
        validate(q=quote(bid_price=D("9900"), ask_price=D("10100")))

def test_quantity_step_mismatch_rejected():
    cfg=SimpleNamespace(max_order_quantity=D("0.01"), max_order_notional_usdt=D("25"), max_leverage=3, max_open_positions=1, validate=lambda: None)
    with pytest.raises(TradeBridgeRiskError, match="quantity filters"):
        validate(p=preview(quantity=D("0.0015")), cfg=cfg)

def test_quantity_above_config_cap_rejected():
    cfg=SimpleNamespace(max_order_quantity=D("0.0005"), max_order_notional_usdt=D("25"), max_leverage=3, max_open_positions=1, validate=lambda: None)
    with pytest.raises(TradeBridgeRiskError, match="configured safety bounds"):
        validate(cfg=cfg)

def test_minimum_notional_rejected():
    with pytest.raises(TradeBridgeRiskError, match="below the exchange minimum"):
        validate(r=rules(min_notional_usdt=D("50")))

def test_max_notional_rejected():
    cfg=SimpleNamespace(max_order_quantity=D("0.01"), max_order_notional_usdt=D("25"), max_leverage=3, max_open_positions=1, validate=lambda: None)
    with pytest.raises(TradeBridgeRiskError, match="configured safety cap"):
        validate(p=preview(quantity=D("0.003")), cfg=cfg)

def test_tick_size_mismatch_rejected():
    with pytest.raises(TradeBridgeRiskError, match="tick-size"):
        validate(p=preview(stop_loss_price=D("9990.05")), r=rules(tick_size=D("0.1")))

def test_entry_slippage_from_mark_rejected():
    with pytest.raises(TradeBridgeRiskError, match="slippage bound"):
        validate(p=preview(entry_reference=D("10060")))

def test_long_stop_must_be_below_current_mark():
    with pytest.raises(TradeBridgeRiskError, match="Long stop"):
        validate(p=preview(stop_loss_price=D("10000")))

def test_short_stop_and_take_profit_geometry():
    p=preview(direction="SHORT", stop_loss_price=D("10010"), take_profit_price=D("9900"))
    assert validate(p=p).direction == "SHORT"
    with pytest.raises(TradeBridgeRiskError, match="Short stop"):
        validate(p=preview(direction="SHORT", stop_loss_price=D("9990"), take_profit_price=D("9900")))

def test_leverage_above_configured_cap_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Leverage"):
        validate(p=preview(leverage=4))

def test_open_position_cap_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Maximum open-position"):
        validate(a=account(open_positions_count=1))

def test_margin_shortfall_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Insufficient available margin"):
        validate(a=account(available_margin_usdt=D("4")))

def test_per_trade_risk_limit_rejected():
    p=preview(stop_loss_price=D("0.1"))
    a=account(equity_usdt=D("500"))
    with pytest.raises(TradeBridgeRiskError, match="per-trade risk cap"):
        validate(p=p, a=a)

def test_total_portfolio_risk_limit_rejected():
    with pytest.raises(TradeBridgeRiskError, match="portfolio risk cap"):
        validate(a=account(current_open_risk_usdt=D("20")))

def test_naive_quote_time_rejected():
    with pytest.raises(TradeBridgeRiskError, match="timezone-aware"):
        validate(q=quote(updated_at=datetime(2026,11,28,15,0)))

def test_nan_market_price_rejected():
    with pytest.raises(TradeBridgeRiskError, match="finite"):
        validate(q=quote(mark_price=D("NaN")))

def test_invalid_exchange_rules_rejected():
    with pytest.raises(TradeBridgeRiskError, match="quantity rules"):
        validate(r=rules(step_size=D("0")))

def test_stale_account_snapshot_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Account risk snapshot data is stale"):
        validate(a=account(updated_at=NOW-timedelta(seconds=6)))

def test_stale_exchange_rules_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Exchange rules data is stale"):
        validate(r=rules(updated_at=NOW-timedelta(hours=2)))

def test_existing_portfolio_over_risk_limit_rejected():
    with pytest.raises(TradeBridgeRiskError, match="Existing portfolio risk"):
        validate(a=account(current_open_risk_usdt=D("21")))

def test_available_margin_cannot_exceed_equity():
    with pytest.raises(TradeBridgeRiskError, match="Account risk snapshot is invalid"):
        validate(a=account(available_margin_usdt=D("1001")))
