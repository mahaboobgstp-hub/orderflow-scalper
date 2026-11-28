from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from app.tradebridge.config import TradeBridgeConfig
from app.tradebridge.models import Direction, OpportunitySignal, PreviewStatus, TakePositionAuthorization, TradePreview
from app.tradebridge.signal_store import SignalStore


NOW = datetime(2026, 11, 28, 15, 0, tzinfo=timezone.utc)
LAYERS = {f"Layer {i}": f"PASS {i}" for i in range(1, 10)}

def signal(**overrides):
    data = {
        "signal_id": "signal-001",
        "symbol": "btcusdt",
        "direction": Direction.LONG,
        "entry_reference": Decimal("100"),
        "created_at": NOW,
        "expires_at": NOW + timedelta(seconds=90),
        "analysis_summary": "Nine-layer paper/testnet candidate",
        "layer_results": LAYERS,
    }
    data.update(overrides)
    return OpportunitySignal(**data)

def preview(**overrides):
    data = {
        "preview_id": "preview-001",
        "signal_id": "signal-001",
        "symbol": "BTCUSDT",
        "direction": Direction.LONG,
        "quantity": Decimal("0.001"),
        "entry_reference": Decimal("100"),
        "stop_loss_price": Decimal("99"),
        "take_profit_price": Decimal("102"),
        "leverage": 1,
        "max_slippage_bps": 50,
        "created_at": NOW,
        "expires_at": NOW + timedelta(seconds=60),
    }
    data.update(overrides)
    return TradePreview(**data)

def auth(p, phrase="TAKE POSITION", hash_value=None):
    return TakePositionAuthorization(preview_id=p.preview_id, trade_hash=hash_value or p.trade_hash, confirmation_phrase=phrase)


def test_default_config_is_disabled_and_testnet_only():
    cfg = TradeBridgeConfig()
    cfg.validate()
    assert not cfg.enabled
    assert not cfg.demo_execution_enabled
    assert not cfg.live_execution_enabled
    assert cfg.testnet
    assert not cfg.execution_available

def test_config_rejects_live_execution():
    with pytest.raises(ValueError, match="live execution is prohibited"):
        TradeBridgeConfig(live_execution_enabled=True).validate()

def test_config_rejects_non_testnet_mode():
    with pytest.raises(ValueError, match="requires Testnet"):
        TradeBridgeConfig(testnet=False).validate()

def test_config_rejects_live_binance_endpoint():
    with pytest.raises(ValueError, match="Demo Futures host"):
        TradeBridgeConfig(binance_base_url="https://fapi.binance.com").validate()

def test_config_rejects_http_endpoint():
    with pytest.raises(ValueError, match="Demo Futures host"):
        TradeBridgeConfig(binance_base_url="http://demo-fapi.binance.com").validate()

def test_config_rejects_url_credentials():
    with pytest.raises(ValueError, match="Demo Futures host"):
        TradeBridgeConfig(binance_base_url="https://user:pass@demo-fapi.binance.com").validate()

def test_config_rejects_extra_path():
    with pytest.raises(ValueError, match="Demo Futures host"):
        TradeBridgeConfig(binance_base_url="https://demo-fapi.binance.com/api").validate()

def test_config_rejects_ttl_outside_bound():
    with pytest.raises(ValueError, match="signal TTL"):
        TradeBridgeConfig(signal_ttl_seconds=301).validate()

def test_config_rejects_preview_ttl_outside_bound():
    with pytest.raises(ValueError, match="preview TTL"):
        TradeBridgeConfig(preview_ttl_seconds=121).validate()

def test_config_rejects_positions_outside_bound():
    with pytest.raises(ValueError, match="max open positions"):
        TradeBridgeConfig(max_open_positions=4).validate()

def test_config_rejects_notional_above_cap():
    with pytest.raises(ValueError, match="max order notional"):
        TradeBridgeConfig(max_order_notional_usdt=101).validate()

def test_config_rejects_execution_without_feature_enabled():
    with pytest.raises(ValueError, match="explicitly enabled"):
        TradeBridgeConfig(demo_execution_enabled=True, enabled=False).validate()

def test_signal_symbol_normalizes_to_uppercase():
    assert signal().symbol == "BTCUSDT"

def test_signal_rejects_non_usdt_symbol():
    with pytest.raises(ValueError, match="USDT-margined"):
        signal(symbol="BTCUSD")

def test_signal_requires_all_nine_layer_keys():
    with pytest.raises(ValueError, match="Exactly one result for each"):
        signal(layer_results={"L1":"pass"})

def test_signal_rejects_duplicate_layer_keys():
    data = {"Layer 1":"pass", "L1":"pass", **{f"Layer {i}":"pass" for i in range(2,10)}}
    with pytest.raises(ValueError, match="Duplicate layer"):
        signal(layer_results=data)

def test_signal_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="timezone"):
        signal(created_at=datetime(2026,11,28,15,0))

def test_signal_rejects_ttl_over_five_minutes():
    with pytest.raises(ValueError, match="lifetime"):
        signal(expires_at=NOW+timedelta(seconds=301))

def test_signal_freshness_boundary():
    s=signal()
    assert s.is_fresh(NOW)
    assert s.is_fresh(NOW+timedelta(seconds=89))
    assert not s.is_fresh(NOW+timedelta(seconds=90))
    assert not s.is_fresh(NOW-timedelta(seconds=1))

def test_preview_requires_long_stop_below_entry():
    with pytest.raises(ValueError, match="Long stop-loss"):
        preview(stop_loss_price=Decimal("100"))

def test_preview_requires_long_take_profit_above_entry():
    with pytest.raises(ValueError, match="Long take-profit"):
        preview(take_profit_price=Decimal("99.5"))

def test_preview_requires_short_stop_above_entry():
    with pytest.raises(ValueError, match="Short stop-loss"):
        preview(direction=Direction.SHORT, stop_loss_price=Decimal("99"), take_profit_price=Decimal("98"))

def test_preview_rejects_leverage_above_three():
    with pytest.raises(ValueError):
        preview(leverage=4)

def test_duplicate_signal_id_rejected():
    store=SignalStore(); store.register(signal(), NOW)
    with pytest.raises(ValueError, match="Duplicate signal"):
        store.register(signal(), NOW)

def test_expired_signal_not_registered():
    store=SignalStore()
    with pytest.raises(ValueError, match="expired or future"):
        store.register(signal(created_at=NOW-timedelta(seconds=2), expires_at=NOW-timedelta(seconds=1)), NOW)

def test_preview_requires_existing_signal():
    with pytest.raises(ValueError, match="unknown signal"):
        SignalStore().register_preview(preview(), NOW)

def test_preview_signal_symbol_direction_must_match():
    store=SignalStore(); store.register(signal(), NOW)
    with pytest.raises(ValueError, match="does not match"):
        store.register_preview(preview(symbol="ETHUSDT"), NOW)

def test_preview_rejects_entry_drift_beyond_slippage_bound():
    store=SignalStore(); store.register(signal(), NOW)
    with pytest.raises(ValueError, match="slippage bound"):
        store.register_preview(preview(entry_reference=Decimal("100.60"), max_slippage_bps=50), NOW)

def test_one_preview_per_signal():
    store=SignalStore(); store.register(signal(), NOW); store.register_preview(preview(), NOW)
    with pytest.raises(ValueError, match="already exists"):
        store.register_preview(preview(preview_id="preview-002"), NOW)

def test_preview_hash_changes_when_quantity_changes():
    assert preview().trade_hash != preview(quantity=Decimal("0.002"), preview_id="preview-002").trade_hash

def test_approval_requires_exact_phrase_and_hash():
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    with pytest.raises(ValueError, match="trade hash"):
        store.authorize(auth(p, hash_value="0"*64), NOW)
    with pytest.raises(ValueError, match="confirmation_phrase"):
        auth(p, phrase="take position")
    approved=store.authorize(auth(p), NOW)
    assert approved.status == PreviewStatus.APPROVED
    assert approved.approved_at == NOW

def test_stale_preview_cannot_be_approved():
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    with pytest.raises(ValueError, match="stale"):
        store.authorize(auth(p), NOW+timedelta(seconds=61))

def test_submission_can_begin_only_once():
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    store.authorize(auth(p), NOW)
    started=store.begin_submission(p.preview_id, NOW)
    assert started.status == PreviewStatus.SUBMITTING
    with pytest.raises(ValueError, match="not been approved|already consumed"):
        store.begin_submission(p.preview_id, NOW)

def test_execution_summary_is_allowlisted_and_redacted():
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    store.authorize(auth(p), NOW); store.begin_submission(p.preview_id, NOW)
    result=store.mark_executed(p.preview_id, {"orderId":123, "status":"NEW", "symbol":"BTCUSDT", "side":"BUY", "executedQty":"0", "avgPrice":"0", "apiKey":"secret", "signature":"secret"}, NOW)
    assert result.status == PreviewStatus.EXECUTED
    assert "apiKey" not in result.execution_summary
    assert "signature" not in result.execution_summary

def test_failed_submission_is_terminal_for_preview():
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    store.authorize(auth(p), NOW); store.begin_submission(p.preview_id, NOW)
    failed=store.mark_failed(p.preview_id, "network timeout / secret=abc", NOW)
    assert failed.status == PreviewStatus.FAILED
    assert failed.execution_summary["error_code"] == "SUBMISSION_FAILED"
    with pytest.raises(ValueError, match="submission state"):
        store.mark_failed(p.preview_id, "again", NOW)

def test_cancel_pending_preview_and_reject_cancel_after_submit():
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    cancelled=store.cancel(p.preview_id, NOW)
    assert cancelled.status == PreviewStatus.CANCELLED
    signal2=signal(signal_id="signal-002")
    store.register(signal2, NOW)
    p2=preview(preview_id="preview-002", signal_id="signal-002")
    store.register_preview(p2, NOW)
    store.authorize(auth(p2), NOW); store.begin_submission(p2.preview_id, NOW)
    with pytest.raises(ValueError, match="after submission"):
        store.cancel(p2.preview_id, NOW)

def test_audit_events_capture_approval_and_submission_without_credentials():
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    store.authorize(auth(p), NOW); store.begin_submission(p.preview_id, NOW)
    names=[e["event"] for e in store.events()]
    assert names == ["SIGNAL_REGISTERED", "PREVIEW_CREATED", "PREVIEW_APPROVED", "SUBMISSION_STARTED"]
    assert all("secret" not in str(e).lower() for e in store.events())

def test_demo_execution_available_only_when_all_gates_are_true():
    cfg=TradeBridgeConfig(enabled=True, demo_execution_enabled=True)
    cfg.validate()
    assert cfg.execution_available
    assert not TradeBridgeConfig(enabled=True, demo_execution_enabled=False).execution_available
    assert not TradeBridgeConfig(enabled=False, demo_execution_enabled=True).execution_available

def test_execution_available_fails_closed_for_invalid_endpoint():
    cfg=TradeBridgeConfig(enabled=True, demo_execution_enabled=True, binance_base_url="https://fapi.binance.com")
    assert not cfg.execution_available

def test_future_signal_is_not_registered():
    store=SignalStore()
    future=signal(created_at=NOW+timedelta(seconds=5), expires_at=NOW+timedelta(seconds=60))
    with pytest.raises(ValueError, match="expired or future"):
        store.register(future, NOW)

def test_preview_cannot_be_registered_with_preapproved_or_execution_state():
    store=SignalStore(); store.register(signal(), NOW)
    with pytest.raises(ValueError, match="new preview must start pending"):
        store.register_preview(preview(status=PreviewStatus.APPROVED, approved_at=NOW), NOW)

def test_approval_is_one_time():
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    store.authorize(auth(p), NOW)
    with pytest.raises(ValueError, match="not pending"):
        store.authorize(auth(p), NOW)

def test_submission_rejects_expired_approved_preview():
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    store.authorize(auth(p), NOW)
    with pytest.raises(ValueError, match="stale"):
        store.begin_submission(p.preview_id, NOW+timedelta(seconds=61))

def test_store_rejects_duplicate_preview_id():
    store=SignalStore(); store.register(signal(), NOW); store.register_preview(preview(), NOW)
    store.register(signal(signal_id="signal-002"), NOW)
    with pytest.raises(ValueError, match="Duplicate preview"):
        store.register_preview(preview(signal_id="signal-002"), NOW)

def test_store_event_details_are_returned_as_copies():
    store=SignalStore(); store.register(signal(), NOW)
    rows=store.events()
    rows[0]["details"]["injected"]="secret"
    assert "injected" not in store.events()[0]["details"]

def test_execution_result_cannot_be_recorded_before_submission():
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    with pytest.raises(ValueError, match="submission state"):
        store.mark_executed(p.preview_id, {"orderId":1}, NOW)


def test_threaded_submission_claim_has_single_winner():
    from concurrent.futures import ThreadPoolExecutor
    store=SignalStore(); store.register(signal(), NOW); p=store.register_preview(preview(), NOW)
    store.authorize(auth(p), NOW)
    def claim():
        try:
            store.begin_submission(p.preview_id, NOW)
            return "claimed"
        except ValueError:
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _: claim(), range(2)))
    assert sorted(results) == ["claimed", "rejected"]
