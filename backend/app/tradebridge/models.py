"""Strict TradeBridge signal, preview, and exact-approval schemas."""
from __future__


from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
import re
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator



class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PreviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUBMITTING = "SUBMITTING"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone.")
    return value.astimezone(timezone.utc)


def _symbol(value: str) -> str:
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,20}USDT", value):
        raise ValueError("TradeBridge supports USDT-margined symbols only.")
    return value


def _decimal_finite(value: Decimal, field_name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite.")
    return value

class OpportunitySignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


    signal_id: str = Field(min_length=8, max_length=128)
    symbol: str
    direction: Direction
    entry_reference: Decimal = Field(gt=0)
    created_at: datetime
    expires_at: datetime
    analysis_summary: str = Field(min_length=1, max_length=2000)
    layer_results: dict[str, str]

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _symbol(value)

    @field_validator("entry_reference")
    @classmethod
    def finite_entry(cls, value: Decimal) -> Decimal:
        return _decimal_finite(value, "entry_reference")

    @field_validator("created_at", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: datetime, info) -> datetime:
        return _require_aware(value, info.field_name)

    @field_validator("layer_results")
    @classmethod
    def validate_layers(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, result in value.items():
            match = re.fullmatch(r"(?:layer|l)[ _-]?([1-9])", key.strip().lower())
            if not match:
                raise ValueError("Layer keys must identify layers 1 through 9.")
            number = int(match.group(1))
            canonical = f"layer_{number}"
            if canonical in normalized:
                raise ValueError("Duplicate layer result.")
            if not isinstance(result, str) or not result.strip() or len(result) > 200:
                raise ValueError("Each layer result must be a non-empty string of at most 200 characters.")
            normalized[canonical] = result.strip()
        if set(normalized) != {f"layer_{i}" for i in range(1, 10)}:
            raise ValueError("Exactly one result for each of the nine layers is required.")
        return normalized

    @model_validator(mode="after")
    def validate_time_window(self):
        if self.expires_at <= self.created_at:
            raise ValueError("Signal expiry must be after creation.")
        if (self.expires_at - self.created_at).total_seconds() > 300:
            raise ValueError("Signal lifetime must not exceed 300 seconds.")
        return self


    def is_fresh(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        return self.created_at <= now < self.expires_at


class TradePreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


    preview_id: str = Field(min_length=8, max_length=128)
    signal_id: str = Field(min_length=8, max_length=128)
    symbol: str
    direction: Direction
    quantity: Decimal = Field(gt=0)
    entry_reference: Decimal = Field(gt=0)
    stop_loss_price: Decimal = Field(gt=0)
    take_profit_price: Decimal | None = Field(default=None, gt=0)
    leverage: int = Field(default=1, ge=1, le=3)
    max_slippage_bps: int = Field(default=50, ge=0, le=100)
    created_at: datetime
    expires_at: datetime
    status: PreviewStatus = PreviewStatus.PENDING
    approved_at: datetime | None = None
    exchange_order_id: str | None = None
    execution_summary: dict[str, str] = Field(default_factory=dict)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        return _symbol(value)

    @field_validator("quantity", "entry_reference", "stop_loss_price")
    @classmethod
    def validate_finite_required(cls, value: Decimal, info) -> Decimal:
        return _decimal_finite(value, info.field_name)


    @field_validator("take_profit_price")
    @classmethod
    def validate_finite_optional(cls, value: Decimal | None) -> Decimal | None:
        if value is not None:
            return _decimal_finite(value, "take_profit_price")
        return value

    @field_validator("created_at", "expires_at", "approved_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        return _require_aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_trade_geometry(self):
        if self.expires_at <= self.created_at:
            raise ValueError("Preview expiry must be after creation.")
        if self.status != PreviewStatus.PENDING or self.approved_at is not None or self.exchange_order_id is not None or self.execution_summary:
            raise ValueError("A new preview must start pending without approval or execution metadata.")
        if (self.expires_at - self.created_at).total_seconds() > 120:
            raise ValueError("Preview lifetime must not exceed 120 seconds.")
        if self.direction == Direction.LONG:
            if self.stop_loss_price >= self.entry_reference:
                raise ValueError("Long stop-loss must be below the entry reference.")
            if self.take_profit_price is not None and self.take_profit_price <= self.entry_reference:
                raise ValueError("Long take-profit must be above the entry reference.")
        else:
            if self.stop_loss_price <= self.entry_reference:
                raise ValueError("Short stop-loss must be above the entry reference.")
            if self.take_profit_price is not None and self.take_profit_price >= self.entry_reference:
                raise ValueError("Short take-profit must be below the entry reference.")
        return self

    def is_fresh(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        return self.created_at <= now < self.expires_at

    @property
    def trade_hash(self) -> str:
        payload = {
            "preview_id": self.preview_id,
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "quantity": format(self.quantity.normalize(), "f"),
            "entry_reference": format(self.entry_reference.normalize(), "f"),
            "stop_loss_price": format(self.stop_loss_price.normalize(), "f"),
            "take_profit_price": format(self.take_profit_price.normalize(), "f") if self.take_profit_price is not None else None,
            "leverage": self.leverage,
            "max_slippage_bps": self.max_slippage_bps,
            "expires_at": self.expires_at.isoformat(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TakePositionAuthorization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    preview_id: str = Field(min_length=8, max_length=128)
    trade_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation_phrase: str = Field(pattern=r"^TAKE POSITION$")
