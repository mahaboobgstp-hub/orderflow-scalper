"""Authenticated TradeBridge preview/approval API. No order submission routes."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.tradebridge.config import TradeBridgeConfig
from app.tradebridge.models import (
    Direction, OpportunitySignal, TradePreview, TakePositionAuthorization, PreviewStatus,
)
from app.tradebridge.risk import validate_preview_risk, TradeBridgeRiskError
from app.tradebridge.snapshot_provider import TradeBridgeSnapshotProvider, SnapshotProviderError
from app.tradebridge.signal_store import SignalStore
from app.execution.binance_demo_client import BinanceDemoError
from app.services.operator_control import _auth as control_auth

router = APIRouter(prefix="/api/tradebridge", tags=["tradebridge-preview"])


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal_id: str | None = Field(default=None, min_length=8, max_length=128)
    symbol: str = Field(min_length=3, max_length=20)
    direction: Direction
    quantity: Decimal = Field(gt=0)
    stop_loss_price: Decimal = Field(gt=0)
    take_profit_price: Decimal | None = Field(default=None, gt=0)
    leverage: int = Field(default=1, ge=1, le=3)
    max_slippage_bps: int = Field(default=50, ge=0, le=100)
    analysis_summary: str = Field(min_length=1, max_length=2000)
    layer_results: dict[str, str]


class PreviewAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trade_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_phrase: str = Field(pattern=r"^TAKE POSITION$")


class TradeBridgePreviewService:
    """Create and approve in-memory previews after server-side risk validation."""
    def __init__(self, *, config: TradeBridgeConfig | None = None,
                 provider: Any | None = None, store: SignalStore | None = None):
        self.config = config or TradeBridgeConfig()
        self.provider = provider or TradeBridgeSnapshotProvider(config=self.config)
        self.store = store or SignalStore()

    def _require_enabled(self) -> None:
        if not self.config.enabled:
            raise HTTPException(status_code=503, detail="TradeBridge previews are disabled.")
        try:
            self.config.validate()
        except (TypeError, ValueError):
            raise HTTPException(status_code=503, detail="TradeBridge configuration is invalid.") from None

    async def create_preview(self, request: PreviewRequest) -> dict[str, Any]:
        self._require_enabled()
        now = datetime.now(timezone.utc)
        try:
            quote, rules, account = await self.provider.fetch(request.symbol)
            signal = OpportunitySignal(
                signal_id=request.signal_id or f"tb-{uuid4().hex}",
                symbol=request.symbol,
                direction=request.direction,
                entry_reference=quote.mark_price,
                created_at=now,
                expires_at=now + timedelta(seconds=self.config.signal_ttl_seconds),
                analysis_summary=request.analysis_summary,
                layer_results=request.layer_results,
            )
            preview = TradePreview(
                preview_id=f"tb-{uuid4().hex}",
                signal_id=signal.signal_id,
                symbol=signal.symbol,
                direction=signal.direction,
                quantity=request.quantity,
                entry_reference=quote.mark_price,
                stop_loss_price=request.stop_loss_price,
                take_profit_price=request.take_profit_price,
                leverage=request.leverage,
                max_slippage_bps=request.max_slippage_bps,
                created_at=now,
                expires_at=now + timedelta(seconds=self.config.preview_ttl_seconds),
            )
            validated = validate_preview_risk(preview, quote, rules, account, self.config, now=now)
            self.store.register(signal, now=now)
            self.store.register_preview(preview, now=now)
        except HTTPException:
            raise
        except (SnapshotProviderError, TradeBridgeRiskError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)[:240]) from None
        except BinanceDemoError:
            raise HTTPException(status_code=503, detail="Demo snapshot unavailable; approval rejected.") from None
        except Exception:
            # Fail closed and keep signed API/network details out of the response.
            raise HTTPException(status_code=503, detail="Trusted Demo snapshots unavailable; approval rejected.") from None
        except BinanceDemoError:
            raise HTTPException(status_code=503, detail="Demo snapshot unavailable; preview rejected.") from None
        except Exception:
            # Provider/network/internal failures must not leak signed request details.
            raise HTTPException(status_code=503, detail="Trusted Demo snapshots unavailable; preview rejected.") from None
        return {
            "preview": preview.model_dump(mode="json"),
            "trade_hash": preview.trade_hash,
            "risk": {
                "notional_usdt": str(validated.notional_usdt),
                "required_margin_usdt": str(validated.required_margin_usdt),
                "stop_risk_usdt": str(validated.stop_risk_usdt),
                "spread_bps": str(validated.spread_bps),
                "quote_age_seconds": validated.quote_age_seconds,
                "account_age_seconds": validated.account_age_seconds,
                "exchange_rules_age_seconds": validated.exchange_rules_age_seconds,
            },
        }

    async def authorize(self, preview_id: str, body: PreviewAuthorizationRequest) -> dict[str, Any]:
        self._require_enabled()
        preview = self.store.get_preview(preview_id)
        if preview is None:
            raise HTTPException(status_code=404, detail="Preview not found.")
        if preview.status != PreviewStatus.PENDING:
            raise HTTPException(status_code=409, detail="Preview is not pending approval.")
        now = datetime.now(timezone.utc)
        if not preview.is_fresh(now):
            raise HTTPException(status_code=409, detail="Preview has expired; authorization is refused.")
        try:
            quote, rules, account = await self.provider.fetch(preview.symbol)
            validate_preview_risk(preview, quote, rules, account, self.config, now=now)
            authorized = self.store.authorize(
                TakePositionAuthorization(
                    preview_id=preview_id,
                    trade_hash=body.trade_hash,
                    confirmation_phrase=body.confirmation_phrase,
                ),
                now=now,
            )
        except HTTPException:
            raise
        except (SnapshotProviderError, BinanceDemoError, TradeBridgeRiskError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)[:240]) from None
        except Exception:
            # Fail closed and keep signed API/network details out of the response.
            raise HTTPException(status_code=503, detail="Trusted Demo snapshots unavailable; approval rejected.") from None
        return {
            "preview": authorized.model_dump(mode="json"),
            "trade_hash": authorized.trade_hash,
            "authorized": True,
            "execution_submitted": False,
        }


async def _service(request: Request) -> TradeBridgePreviewService:
    service = getattr(request.app.state, "tradebridge_preview_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="TradeBridge preview service is unavailable.")
    return service


def _require_auth(token: str | None) -> None:
    control_auth(token)


@router.post("/preview")
async def create_trade_preview(body: PreviewRequest, request: Request,
                              x_control_token: str | None = Header(default=None)):
    _require_auth(x_control_token)
    service = await _service(request)
    return await service.create_preview(body)


@router.get("/preview/{preview_id}")
async def get_trade_preview(preview_id: str, request: Request,
                           x_control_token: str | None = Header(default=None)):
    _require_auth(x_control_token)
    service = await _service(request)
    preview = service.store.get_preview(preview_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview not found.")
    return {"preview": preview.model_dump(mode="json"), "trade_hash": preview.trade_hash}


@router.post("/preview/{preview_id}/authorize")
async def authorize_trade_preview(preview_id: str, body: PreviewAuthorizationRequest,
                                 request: Request, x_control_token: str | None = Header(default=None)):
    _require_auth(x_control_token)
    service = await _service(request)
    return await service.authorize(preview_id, body)


@router.delete("/preview/{preview_id}")
async def cancel_trade_preview(preview_id: str, request: Request,
                             x_control_token: str | None = Header(default=None)):
    _require_auth(x_control_token)
    service = await _service(request)
    try:
        preview = service.store.cancel(preview_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {
        "preview": preview.model_dump(mode="json"),
        "cancelled": True,
        "execution_submitted": False,
    }


@router.get("/audit")
async def tradebridge_audit(request: Request, limit: int = 100,
                           x_control_token: str | None = Header(default=None)):
    _require_auth(x_control_token)
    service = await _service(request)
    return {"events": service.store.events(limit=max(1, min(int(limit), 500)))}
