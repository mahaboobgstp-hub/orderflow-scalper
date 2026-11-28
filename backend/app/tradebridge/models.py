"""Typed models for validated opportunities and authorization requests."""
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class OpportunitySignal(BaseModel):
    signal_id: str = Field(min_length=8, max_length=128)
    symbol: str = Field(min_length=3, max_length=24)
    direction: Direction
    entry_reference: float = Field(gt=0)
    created_at: datetime
    expires_at: datetime
    analysis_summary: str = Field(min_length=1, max_length=2000)
    layer_results: dict[str, str]
    approved: bool = False

    def is_fresh(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        created = self.created_at if self.created_at.tzinfo else self.created_at.replace(tzinfo=timezone.utc)
        expiry = self.expires_at if self.expires_at.tzinfo else self.expires_at.replace(tzinfo=timezone.utc)
        return created <= now < expiry

class TakePositionAuthorization(BaseModel):
    signal_id: str = Field(min_length=8, max_length=128)
    confirmation_phrase: str = Field(pattern=r"(?i)^take position$")
