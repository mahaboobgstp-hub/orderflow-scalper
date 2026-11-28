"""Focused API tests; provider is mocked and no exchange order is ever sent."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.tradebridge.routes import router, TradeBridgePreviewService
from app.tradebridge.models import PreviewStatus
from app.tradebridge.risk import MarketQuote, SymbolRules, AccountRisk
from app.tradebridge.signal_store import SignalStore

TOKEN = "route-test-token"


class ConfigStub:
    enabled = True
    signal_ttl_seconds = 90
    preview_ttl_seconds = 60
    max_open_positions = 1
    max_order_notional_usdt = Decimal("25")
    max_order_quantity = Decimal("1")
    max_leverage = 3

    def validate(self):
        return None


class ProviderStub:
    def __init__(self, *, quote_age=0, equity=Decimal("10000")):
        self.quote_age = quote_age
        self.equity = equity
        self.calls = 0

    async def fetch(self, symbol):
        self.calls += 1
        now = datetime.now(timezone.utc)
        quote = MarketQuote(
            symbol=symbol, mark_price=Decimal("100"), bid_price=Decimal("99.99"),
            ask_price=Decimal("100.01"), updated_at=now-timedelta(seconds=self.quote_age),
        )
        rules = SymbolRules(
            symbol=symbol, min_quantity=Decimal("0.01"), max_quantity=Decimal("10"),
            step_size=Decimal("0.01"), min_notional_usdt=Decimal("5"),
            tick_size=Decimal("0.01"), updated_at=now,
        )
        account = AccountRisk(
            equity_usdt=self.equity, available_margin_usdt=self.equity,
            open_positions_count=0, current_open_risk_usdt=Decimal("0"), updated_at=now,
        )
        return quote, rules, account


def setup(provider=None, config=None):
    service = TradeBridgePreviewService(
        config=config or ConfigStub(), provider=provider or ProviderStub(), store=SignalStore(),
    )
    app = FastAPI()
    app.include_router(router)
    app.state.tradebridge_preview_service = service
    return TestClient(app), service


def payload(**updates):
    data = {
        "signal_id": "route-signal-0001",
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "quantity": "0.10",
        "stop_loss_price": "99.00",
        "take_profit_price": "101.00",
        "leverage": 1,
        "max_slippage_bps": 50,
        "analysis_summary": "test-only signal; layer annotations are untrusted",
        "layer_results": {f"layer_{i}": f"layer {i} fixture" for i in range(1, 10)},
    }
    data.update(updates)
    return data


def headers():
    return {"X-Control-Token": TOKEN}


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    monkeypatch.setenv("CONTROL_API_TOKEN", TOKEN)


def test_preview_uses_server_mark_and_returns_hash_and_risk():
    client, service = setup()
    response = client.post("/api/tradebridge/preview", json=payload(), headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert body["preview"]["entry_reference"] == "100"
    assert body["preview"]["status"] == "PENDING"
    assert len(body["trade_hash"]) == 64
    assert Decimal(body["risk"]["notional_usdt"]) == Decimal("10.00")
    assert service.store.get_preview(body["preview"]["preview_id"]) is not None


def test_preview_fails_when_bridge_disabled():
    config = ConfigStub()
    config.enabled = False
    provider = ProviderStub()
    client, _ = setup(provider=provider, config=config)
    response = client.post("/api/tradebridge/preview", json=payload(), headers=headers())
    assert response.status_code == 503
    assert provider.calls == 0


def test_stale_quote_rejected_without_registering_signal():
    provider = ProviderStub(quote_age=3)
    client, service = setup(provider=provider)
    response = client.post("/api/tradebridge/preview", json=payload(), headers=headers())
    assert response.status_code == 409
    assert service.store.get("route-signal-0001") is None


def test_stop_risk_above_cap_rejected():
    client, service = setup(provider=ProviderStub(equity=Decimal("10")))
    response = client.post("/api/tradebridge/preview", json=payload(stop_loss_price="98.00"), headers=headers())
    assert response.status_code == 409
    assert service.store.get("route-signal-0001") is None


def test_approval_requires_exact_trade_hash_and_keeps_preview_pending_on_mismatch():
    client, service = setup()
    created = client.post("/api/tradebridge/preview", json=payload(), headers=headers()).json()
    preview_id = created["preview"]["preview_id"]
    bad = client.post(
        f"/api/tradebridge/preview/{preview_id}/authorize",
        json={"trade_hash": "0"*64, "confirmation_phrase": "TAKE POSITION"},
        headers=headers(),
    )
    assert bad.status_code == 409
    assert service.store.get_preview(preview_id).status == PreviewStatus.PENDING
    good = client.post(
        f"/api/tradebridge/preview/{preview_id}/authorize",
        json={"trade_hash": created["trade_hash"], "confirmation_phrase": "TAKE POSITION"},
        headers=headers(),
    )
    assert good.status_code == 200
    assert good.json()["authorized"] is True
    assert good.json()["execution_submitted"] is False
    assert service.store.get_preview(preview_id).status == PreviewStatus.APPROVED


def test_approval_rechecks_freshness_and_does_not_authorize_when_stale():
    provider = ProviderStub()
    client, service = setup(provider=provider)
    created = client.post("/api/tradebridge/preview", json=payload(), headers=headers()).json()
    provider.quote_age = 3
    response = client.post(
        f"/api/tradebridge/preview/{created['preview']['preview_id']}/authorize",
        json={"trade_hash": created["trade_hash"], "confirmation_phrase": "TAKE POSITION"},
        headers=headers(),
    )
    assert response.status_code == 409
    assert service.store.get_preview(created["preview"]["preview_id"]).status == PreviewStatus.PENDING


def test_duplicate_signal_id_rejected():
    client, _ = setup()
    assert client.post("/api/tradebridge/preview", json=payload(), headers=headers()).status_code == 200
    assert client.post("/api/tradebridge/preview", json=payload(), headers=headers()).status_code == 409


def test_cancel_preview_is_local_only():
    client, _ = setup()
    created = client.post("/api/tradebridge/preview", json=payload(), headers=headers()).json()
    response = client.delete(
        f"/api/tradebridge/preview/{created['preview']['preview_id']}", headers=headers(),
    )
    assert response.status_code == 200
    assert response.json()["cancelled"] is True
    assert response.json()["execution_submitted"] is False
    assert response.json()["preview"]["status"] == "CANCELLED"


def test_routes_require_control_token():
    client, _ = setup()
    response = client.post("/api/tradebridge/preview", json=payload())
    assert response.status_code == 401


def test_invalid_confirmation_phrase_rejected_by_schema():
    client, _ = setup()
    response = client.post(
        "/api/tradebridge/preview/preview-id/authorize",
        json={"trade_hash": "0"*64, "confirmation_phrase": "yes"},
        headers=headers(),
    )
    assert response.status_code == 422



def test_provider_failure_is_sanitized_and_preview_is_rejected():
    class FailingProvider:
        async def fetch(self, symbol):
            raise RuntimeError("signed_query=private-secret-value")
    client, _ = setup(provider=FailingProvider())
    response = client.post("/api/tradebridge/preview", json=payload(), headers=headers())
    assert response.status_code == 503
    assert "private-secret-value" not in response.text
    assert "Trusted Demo snapshots unavailable" in response.text


def test_expired_preview_is_rejected_before_another_provider_fetch():
    provider = ProviderStub()
    client, service = setup(provider=provider)
    created = client.post("/api/tradebridge/preview", json=payload(), headers=headers()).json()
    preview_id = created["preview"]["preview_id"]
    stored = service.store.get_preview(preview_id)
    service.store._previews[preview_id] = stored.model_copy(
        update={"expires_at": datetime.now(timezone.utc)-timedelta(seconds=1)}
    )
    response = client.post(
        f"/api/tradebridge/preview/{preview_id}/authorize",
        json={"trade_hash": created["trade_hash"], "confirmation_phrase": "TAKE POSITION"},
        headers=headers(),
    )
    assert response.status_code == 409
    assert provider.calls == 1
    assert service.store.get_preview(preview_id).status == PreviewStatus.PENDING



def test_demo_api_error_is_sanitized():
    from app.execution.binance_demo_client import BinanceDemoError
    class FailingProvider:
        async def fetch(self, symbol):
            raise BinanceDemoError("api_key=never-show-this-value")
    client, _ = setup(provider=FailingProvider())
    response = client.post("/api/tradebridge/preview", json=payload(), headers=headers())
    assert response.status_code == 503
    assert "never-show-this-value" not in response.text


def test_approval_is_one_time_and_second_attempt_does_not_refresh():
    provider = ProviderStub()
    client, service = setup(provider=provider)
    created = client.post("/api/tradebridge/preview", json=payload(), headers=headers()).json()
    pid = created["preview"]["preview_id"]
    approval = {"trade_hash": created["trade_hash"], "confirmation_phrase": "TAKE POSITION"}
    first = client.post(f"/api/tradebridge/preview/{pid}/authorize", json=approval, headers=headers())
    assert first.status_code == 200
    assert provider.calls == 2
    second = client.post(f"/api/tradebridge/preview/{pid}/authorize", json=approval, headers=headers())
    assert second.status_code == 409
    assert provider.calls == 2
    assert service.store.get_preview(pid).status == PreviewStatus.APPROVED
