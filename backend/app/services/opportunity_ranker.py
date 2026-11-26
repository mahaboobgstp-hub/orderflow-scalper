"""Phase C: explainable watchlist opportunity ranking.

This module consumes existing scanner rows and re-ranks them for review. It is
read-only and deliberately emits no buy/sell signal or execution instruction.
"""
from __future__ import annotations

from typing import Any


class OpportunityRanker:
    """Rank scanner rows using bounded, transparent quality proxies."""

    def __init__(self, min_volume_usdt: float = 5_000_000,
                 max_spread_pct: float = 0.12,
                 preferred_range_pct: float = 8.0):
        self.min_volume_usdt = max(float(min_volume_usdt), 1.0)
        self.max_spread_pct = max(float(max_spread_pct), 0.0001)
        self.preferred_range_pct = max(float(preferred_range_pct), 0.1)

    @staticmethod
    def _num(row: dict[str, Any], key: str, default: float = 0.0) -> float:
        try:
            value = float(row.get(key))
            return value if value == value and abs(value) != float("inf") else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _cap(value: float, ceiling: float = 100.0) -> float:
        return max(0.0, min(ceiling, value))

    def rank(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        ranked = []
        for source in rows:
            if not isinstance(source, dict) or not source.get("symbol"):
                continue
            row = dict(source)
            volume = self._num(row, "quote_volume_24h")
            spread = self._num(row, "spread_pct")
            range_pct = self._num(row, "range_24h_pct")
            trades = self._num(row, "trade_count_24h")
            momentum = self._num(row, "price_change_24h_pct")
            accel = row.get("volume_acceleration_ratio_5m")
            try:
                accel = float(accel) if accel is not None else None
                if accel is not None and (accel != accel or abs(accel) == float("inf")):
                    accel = None
            except (TypeError, ValueError):
                accel = None

            volume_score = self._cap(volume / self.min_volume_usdt * 25)
            spread_score = self._cap((self.max_spread_pct / max(spread, 0.0001)) * 20) if spread > 0 else 20
            range_score = self._cap((range_pct / self.preferred_range_pct) * 15)
            activity_score = self._cap(trades / 10000 * 20)
            momentum_score = self._cap((momentum + 10) * 0.75, 15)
            acceleration_score = self._cap((accel or 0) * 5, 5) if accel is not None else 0
            total = round(volume_score + spread_score + range_score + activity_score + momentum_score + acceleration_score, 2)
            flags = []
            if volume < self.min_volume_usdt:
                flags.append("LOW_VOLUME")
            if spread > self.max_spread_pct:
                flags.append("WIDE_SPREAD")
            if range_pct <= 0:
                flags.append("RANGE_UNAVAILABLE")
            if accel is None:
                flags.append("ACTIVITY_ACCELERATION_UNAVAILABLE")
            row["phase_c_score"] = total
            row["phase_c_score_components"] = {
                "volume": round(volume_score, 2),
                "spread": round(spread_score, 2),
                "range": round(range_score, 2),
                "trade_activity": round(activity_score, 2),
                "momentum_proxy": round(momentum_score, 2),
                "activity_acceleration": round(acceleration_score, 2),
            }
            row["phase_c_quality_flags"] = flags
            row["phase_c_review_status"] = "REVIEW_CANDIDATE" if not flags[:2] and range_pct > 0 else "FILTERED"
            row["phase_c_score_note"] = "Heuristic ranking only; not a probability or trade signal."
            ranked.append(row)
        ranked.sort(key=lambda item: item.get("phase_c_score", 0), reverse=True)
        for index, row in enumerate(ranked, start=1):
            row["phase_c_rank"] = index
        return {
            "scanner": "phase_c_opportunity_ranker",
            "mode": "READ_ONLY_PUBLIC_MARKET_DATA",
            "trade_signal": False,
            "execution_enabled": False,
            "candidate_count": sum(1 for row in ranked if row["phase_c_review_status"] == "REVIEW_CANDIDATE"),
            "ranked_count": len(ranked),
            "score_note": "Scores are transparent bounded heuristics and do not predict outcomes.",
            "markets": ranked,
        }
