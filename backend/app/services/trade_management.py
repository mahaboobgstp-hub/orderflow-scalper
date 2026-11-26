"""Phase D paper-only trade management decision engine.

Pure deterministic calculations: no exchange connectivity, order placement, or side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional
import math


@dataclass(frozen=True)
class TradeManagementConfig:
    initial_stop_pct: float = 1.0
    break_even_trigger_pct: float = 0.8
    break_even_offset_pct: float = 0.05
    trailing_stop_pct: float = 0.75
    take_profit_trigger_pct: float = 1.2
    trailing_take_profit_pct: float = 0.5
    trend_extension_score: float = 65.0
    weak_trend_exit_score: float = 25.0
    max_hold_seconds: Optional[int] = None

    def validate(self) -> None:
        for name in (
            "initial_stop_pct", "break_even_trigger_pct", "break_even_offset_pct",
            "trailing_stop_pct", "take_profit_trigger_pct", "trailing_take_profit_pct",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0 or value >= 100:
                raise ValueError(f"{name} must be finite and between 0 and 100")
        for name in ("trend_extension_score", "weak_trend_exit_score"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError(f"{name} must be between 0 and 100")
        if self.max_hold_seconds is not None and self.max_hold_seconds <= 0:
            raise ValueError("max_hold_seconds must be positive when set")


@dataclass(frozen=True)
class ManagementResult:
    symbol: str
    side: str
    mark_price: float
    best_price: float
    favorable_move_pct: float
    adverse_move_pct: float
    initial_stop_price: float
    stop_price: float
    break_even_active: bool
    trailing_stop_active: bool
    trailing_take_profit_active: bool
    trend_extension: bool
    exit_action: str
    exit_reason: Optional[str]
    management_notes: tuple[str, ...]


class TradeManagementEngine:
    """Calculates protective stop/target levels and exit advisories for simulated positions."""

    def __init__(self, config: TradeManagementConfig | None = None):
        self.config = config or TradeManagementConfig()
        self.config.validate()

    @staticmethod
    def _finite(value, label):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{label} must be a finite number")
        if not math.isfinite(number):
            raise ValueError(f"{label} must be a finite number")
        return number

    def evaluate(self, position: dict, market: dict, now_seconds: float | None = None) -> ManagementResult:
        symbol = str(position.get("symbol", "")).upper().strip()
        side = str(position.get("side", "")).lower()
        entry = self._finite(position.get("entry_price"), "entry_price")
        mark = self._finite(market.get("mark_price"), "mark_price")
        best = self._finite(position.get("best_price", entry), "best_price")
        opened = self._finite(position.get("opened_at_seconds", 0), "opened_at_seconds")
        trend = self._finite(market.get("trend_score", 50), "trend_score")
        if not symbol:
            raise ValueError("symbol is required")
        if side not in ("long", "short"):
            raise ValueError("side must be long or short")
        if entry <= 0 or mark <= 0 or best <= 0:
            raise ValueError("prices must be positive")
        if not 0 <= trend <= 100:
            raise ValueError("trend_score must be between 0 and 100")
        favorable = (mark-entry)/entry*100 if side == "long" else (entry-mark)/entry*100
        adverse = max(0.0, -favorable)
        best = max(best, mark) if side == "long" else min(best, mark)
        favorable_best = (best-entry)/entry*100 if side == "long" else (entry-best)/entry*100
        if side == "long":
            initial_stop = entry*(1-self.config.initial_stop_pct/100)
            trail = best*(1-self.config.trailing_stop_pct/100)
            break_even = favorable_best >= self.config.break_even_trigger_pct
            stop = max(initial_stop, trail if favorable_best > 0 else initial_stop, entry*(1+self.config.break_even_offset_pct/100) if break_even else initial_stop)
        else:
            initial_stop = entry*(1+self.config.initial_stop_pct/100)
            trail = best*(1+self.config.trailing_stop_pct/100)
            break_even = favorable_best >= self.config.break_even_trigger_pct
            stop = min(initial_stop, trail if favorable_best > 0 else initial_stop, entry*(1-self.config.break_even_offset_pct/100) if break_even else initial_stop)
        tp_active = favorable_best >= self.config.take_profit_trigger_pct
        tp = best*(1-self.config.trailing_take_profit_pct/100) if side == "long" else best*(1+self.config.trailing_take_profit_pct/100)
        trend_extension = trend >= self.config.trend_extension_score and favorable >= 0
        notes = []
        if break_even:
            notes.append("BREAK_EVEN_PROTECTION_ACTIVE")
        if favorable_best > 0:
            notes.append("FAVORABLE_EXTREME_UPDATED")
        if trend_extension:
            notes.append("TREND_EXTENSION_MODE")
        if tp_active:
            notes.append("TRAILING_TAKE_PROFIT_ACTIVE")
        exit_reason = None
        if (side == "long" and mark <= stop) or (side == "short" and mark >= stop):
            exit_reason = "PROTECTIVE_STOP"
        elif tp_active and ((side == "long" and mark <= tp) or (side == "short" and mark >= tp)):
            exit_reason = "TRAILING_TAKE_PROFIT"
        elif trend <= self.config.weak_trend_exit_score and favorable <= 0:
            exit_reason = "TREND_WEAKENING"
        if self.config.max_hold_seconds is not None and now_seconds is not None and now_seconds-opened >= self.config.max_hold_seconds and not trend_extension:
            exit_reason = exit_reason or "MAX_HOLD_TIME"
        return ManagementResult(
            symbol=symbol, side=side, mark_price=mark,
            favorable_move_pct=round(favorable, 8), adverse_move_pct=round(adverse, 8),
            initial_stop_price=round(initial_stop, 12), stop_price=round(stop, 12),
            break_even_active=break_even, trailing_stop_active=favorable_best > 0,
            trailing_take_profit_active=tp_active, trend_extension=trend_extension,
            exit_action="EXIT" if exit_reason else "HOLD", exit_reason=exit_reason,
            management_notes=tuple(notes),
        )

    def describe(self) -> dict:
        return {"engine": "phase_d_trade_management", "mode": "PAPER_ONLY",
                "side_effects": False, "exchange_execution": False,
                "features": ["initial_stop", "break_even_protection", "trailing_stop_loss",
                             "trailing_take_profit", "trend_extension", "trend_weakening_exit",
                             "optional_max_hold_time"],
                "config": asdict(self.config)}
