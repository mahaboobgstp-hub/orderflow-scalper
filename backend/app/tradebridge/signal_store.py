"""Thread-safe in-memory signal/preview registry with one-time approval semantics.
Persistence is intentionally not implemented here; this store is a safety boundary
for a single process and is not sufficient for a multi-instance execution service.
"""
from __future__


from datetime import datetime, timezone
from copy import deepcopy
from threading import RLock
from typing import Any
import re
from .models import OpportunitySignal, PreviewStatus, TakePositionAuthorization, TradePreview



class SignalStore:
    def __init__(self) -> None:
        self._signals: dict[str, OpportunitySignal] = {}
        self._previews: dict[str, TradePreview] = {}
        self._events: list[dict[str, Any]] = []
        self._lock = RLock()

    @staticmethod
    def _utc(now: datetime | None) -> datetime:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _event(self, name: str, signal_id: str, preview_id: str | None = None, details: dict[str, Any] | None = None, now: datetime | None = None) -> None:
        row = {"event": name, "signal_id": signal_id, "preview_id": preview_id, "at": self._utc(now).isoformat(), "details": details or {}}
        self._events.append(row)
        self._events = self._events[-500:]

    def register(self, signal: OpportunitySignal, now: datetime | None = None) -> OpportunitySignal:
        with self._lock:
            if not signal.is_fresh(now):
                raise ValueError("Cannot register an expired or future signal.")
            if signal.signal_id in self._signals:
                raise ValueError("Duplicate signal ID.")
            self._signals[signal.signal_id] = signal
            self._event("SIGNAL_REGISTERED", signal.signal_id, now=now)
            return signal

    def get(self, signal_id: str) -> OpportunitySignal | None:
        with self._lock:
            return self._signals.get(signal_id)

    def latest(self) -> OpportunitySignal | None:
        with self._lock:
            return next(reversed(self._signals.values()), None) if self._signals else None

    def register_preview(self, preview: TradePreview, now: datetime | None = None) -> TradePreview:
        current = self._utc(now)
        with self._lock:
            signal = self._signals.get(preview.signal_id)
            if signal is None:
                raise ValueError("Preview references an unknown signal.")
            if not signal.is_fresh(current):
                raise ValueError("Preview signal is expired.")
            if not preview.is_fresh(current):
                raise ValueError("Preview is expired or not yet valid.")
            if preview.symbol != signal.symbol or preview.direction != signal.direction:
                raise ValueError("Preview symbol/direction does not match its signal.")
            drift_bps = abs(preview.entry_reference - signal.entry_reference) / signal.entry_reference * 10000
            if drift_bps > preview.max_slippage_bps:
                raise ValueError("Preview entry reference exceeds the signal slippage bound.")
            if preview.preview_id in self._previews:
                raise ValueError("Duplicate preview ID.")
            if any(p.signal_id == preview.signal_id for p in self._previews.values()):
                raise ValueError("A preview already exists for this signal; create a new signal before retrying.")
            self._previews[preview.preview_id] = preview
            self._event("PREVIEW_CREATED", preview.signal_id, preview.preview_id, {"trade_hash": preview.trade_hash}, current)
            return preview

    def get_preview(self, preview_id: str) -> TradePreview | None:
        with self._lock:
            return self._previews.get(preview_id)


    def authorize(self, authorization: TakePositionAuthorization, now: datetime | None = None) -> TradePreview:
        current = self._utc(now)
        with self._lock:
            preview = self._previews.get(authorization.preview_id)
            if preview is None:
                raise ValueError("Unknown preview.")
            signal = self._signals.get(preview.signal_id)
            if signal is None or not signal.is_fresh(current) or not preview.is_fresh(current):
                raise ValueError("Signal or preview is stale; approval is refused.")
            if preview.status != PreviewStatus.PENDING:
                raise ValueError("Preview is not pending approval.")
            if authorization.confirmation_phrase != "TAKE POSITION":
                raise ValueError("Exact confirmation phrase required.")
            if authorization.trade_hash != preview.trade_hash:
                raise ValueError("Approved trade hash does not match the preview.")
            approved = preview.model_copy(update={"status": PreviewStatus.APPROVED, "approved_at": current})
            self._previews[preview.preview_id] = approved
            self._event("PREVIEW_APPROVED", signal.signal_id, preview.preview_id, {"trade_hash": preview.trade_hash}, current)
            return approved

    def begin_submission(self, preview_id: str, now: datetime | None = None) -> TradePreview:
        current = self._utc(now)
        with self._lock:
            preview = self._previews.get(preview_id)
            if preview is None:
                raise ValueError("Unknown preview.")
            signal = self._signals.get(preview.signal_id)
            if signal is None or not signal.is_fresh(current) or not preview.is_fresh(current):
                raise ValueError("Signal or preview is stale; submission is refused.")
            if preview.status != PreviewStatus.APPROVED:
                raise ValueError("Preview has not been approved or was already consumed.")
            submitting = preview.model_copy(update={"status": PreviewStatus.SUBMITTING})
            self._previews[preview_id] = submitting
            self._event("SUBMISSION_STARTED", preview.signal_id, preview_id, {"trade_hash": preview.trade_hash}, current)
            return submitting

    def mark_executed(self, preview_id: str, order_summary: dict[str, Any], now: datetime | None = None) -> TradePreview:
        current = self._utc(now)
        with self._lock:
            preview = self._previews.get(preview_id)
            if preview is None or preview.status != PreviewStatus.SUBMITTING:
                raise ValueError("Preview is not in submission state.")
            allowed = {"orderId", "clientOrderId", "status", "symbol", "side", "executedQty", "avgPrice", "updateTime"}
            sanitized = {k: str(v)[:120] for k, v in order_summary.items() if k in allowed and v is not None}
            executed = preview.model_copy(update={"status": PreviewStatus.EXECUTED, "exchange_order_id": sanitized.get("orderId"), "execution_summary": sanitized})
            self._previews[preview_id] = executed
            self._event("SUBMISSION_EXECUTED", preview.signal_id, preview_id, {"order_id": sanitized.get("orderId"), "status": sanitized.get("status")}, current)
            return executed

    def mark_failed(self, preview_id: str, error_code: str, now: datetime | None = None) -> TradePreview:
        current = self._utc(now)
        with self._lock:
            preview = self._previews.get(preview_id)
            if preview is None or preview.status != PreviewStatus.SUBMITTING:
                raise ValueError("Preview is not in submission state.")
            allowed_codes = {"NETWORK_ERROR", "EXCHANGE_REJECTED", "RISK_REJECTED", "STALE_DATA", "CONFIGURATION_ERROR", "TIMEOUT", "UNKNOWN"}
            candidate_code = re.sub(r"[^A-Z0-9_]+", "_", str(error_code).upper())[:64]
            safe_code = candidate_code if candidate_code in allowed_codes else "SUBMISSION_FAILED"
            failed = preview.model_copy(update={"status": PreviewStatus.FAILED, "execution_summary": {"error_code": safe_code}})
            self._previews[preview_id] = failed
            self._event("SUBMISSION_FAILED", preview.signal_id, preview_id, {"error_code": safe_code}, current)
            return failed

    def cancel(self, preview_id: str, now: datetime | None = None) -> TradePreview:
        current = self._utc(now)
        with self._lock:
            preview = self._previews.get(preview_id)
            if preview is None:
                raise ValueError("Unknown preview.")
            if preview.status not in {PreviewStatus.PENDING, PreviewStatus.APPROVED}:
                raise ValueError("Preview cannot be cancelled after submission begins.")
            cancelled = preview.model_copy(update={"status": PreviewStatus.CANCELLED})
            self._previews[preview_id] = cancelled
            self._event("PREVIEW_CANCELLED", preview.signal_id, preview_id, {}, current)
            return cancelled

    def events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(self._events[-max(1, min(limit, 500)):])

    def clear(self) -> None:
        with self._lock:
            self._signals.clear()
            self._previews.clear()
            self._events.clear()
