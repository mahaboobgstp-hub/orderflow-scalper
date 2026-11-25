"""Phase 5: deterministic order-book imbalance analysis.

This detector is descriptive, not a trading signal. It only accepts synchronized,
fresh normalized books and reports diagnostics alongside pressure metrics.
"""
from __future__ import annotations

import time
import math
from collections import deque
from typing import Any


class OrderBookImbalanceDetector:
    def __init__(
        self,
        *,
        pressure_threshold: float = 0.18,
        history_size: int = 20,
        persistence_window_seconds: float = 15.0,
        max_book_age_seconds: float = 3.0,
    ) -> None:
        self.pressure_threshold = max(0.01, min(float(pressure_threshold), 0.95))
        self.history_size = max(2, min(int(history_size), 200))
        self.persistence_window_seconds = max(1.0, float(persistence_window_seconds))
        self.max_book_age_seconds = max(0.1, float(max_book_age_seconds))
        self._history: dict[str, deque[dict[str, Any]]] = {}

    @staticmethod
    def _levels(raw: Any, side: str) -> list[tuple[float, float]]:
        if not isinstance(raw, list):
            raise ValueError(f"{side} levels must be a list")
        parsed: list[tuple[float, float]] = []
        for row in raw:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            try:
                price, quantity = float(row[0]), float(row[1])
            except (ValueError, TypeError):
                continue
            if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0:
                continue
            parsed.append((price, quantity))
        parsed.sort(key=lambda x: x[0], reverse=(side == "bids"))
        return parsed

    @staticmethod
    def _ratio(bid_qty: float, ask_qty: float) -> float:
        total = bid_qty + ask_qty
        return (bid_qty - ask_qty) / total if total > 0 else 0.0

    @staticmethod
    def _side_metrics(levels: list[tuple[float, float]]) -> dict[str, float]:
        total = sum(q for _, q in levels)
        largest = max((q for _, q in levels), default=0.0)
        return {
            "total_quantity": round(total, 8),
            "largest_level_quantity": round(largest, 8),
            "largest_level_concentration": round(largest / total, 6) if total else 0.0,
        }

    def _record(self, key: str, score: float, now: float) -> list[dict[str, Any]]:
        history = self._history.setdefault(key, deque(maxlen=self.history_size))
        history.append({"timestamp": now, "score": score})
        cutoff = now - self.persistence_window_seconds
        while history and history[0]["timestamp"] < cutoff:
            history.popleft()
        return list(history)

    def analyze(self, book: dict[str, Any], levels: int = 10) -> dict[str, Any]:
        if not isinstance(book, dict):
            raise ValueError("Normalized order book is required.")
        exchange = str(book.get("exchange", "")).lower()
        symbol = str(book.get("symbol", "")).upper()
        if not exchange or not symbol:
            raise ValueError("Order book exchange and symbol are required.")
        if not book.get("synchronized", False):
            raise ValueError("Order book is unsynchronized; imbalance analysis refused.")
        if book.get("stale", True):
            raise ValueError("Order book is stale; imbalance analysis refused.")
        age = book.get("age_seconds")
        if age is None or float(age) > self.max_book_age_seconds:
            raise ValueError("Order book exceeds allowed age; analysis refused.")
        if book.get("integrity_error"):
            raise ValueError(f"Order book integrity error: {book['integrity_error']}")
        requested_levels = max(1, min(int(levels), 20))
        bids = self._levels(book.get("bids"), "bids")[:requested_levels]
        asks = self._levels(book.get("asks"), "asks")[:requested_levels]
        if not bids or not asks:
            raise ValueError("Both bid and ask sides must contain valid levels.")
        best_bid, best_ask = bids[0][0], asks[0][0]
        if best_bid >= best_ask:
            raise ValueError("Crossed or locked order book is invalid for analysis.")

        top_bid_qty, top_ask_qty = bids[0][1], asks[0][1]
        raw_bid_qty, raw_ask_qty = sum(q for _, q in bids), sum(q for _, q in asks)
        # Rank-distance decay: nearer levels contribute more. The same weighting
        # applies to each side and is normalized by the total weights.
        bid_weighted = sum(q / (i + 1) for i, (_, q) in enumerate(bids))
        ask_weighted = sum(q / (i + 1) for i, (_, q) in enumerate(asks))
        raw_score = self._ratio(raw_bid_qty, raw_ask_qty)
        top_score = self._ratio(top_bid_qty, top_ask_qty)
        weighted_score = self._ratio(bid_weighted, ask_weighted)
        key = f"{exchange}:{symbol}"
        now = time.time()
        history = self._record(key, weighted_score, now)
        pressure_change_per_second = None
        pressure_acceleration_per_second2 = None
        if len(history) > 1:
            previous = history[-2]
            dt = max(now - previous["timestamp"], 1e-6)
            pressure_change_per_second = (weighted_score - previous["score"]) / dt
            if len(history) > 2:
                prior = history[-3]
                prior_dt = max(previous["timestamp"] - prior["timestamp"], 1e-6)
                prior_rate = (previous["score"] - prior["score"]) / prior_dt
                pressure_acceleration_per_second2 = (pressure_change_per_second - prior_rate) / max((dt + prior_dt) / 2, 1e-6)
        positive = sum(1 for item in history if item["score"] >= self.pressure_threshold)
        negative = sum(1 for item in history if item["score"] <= -self.pressure_threshold)
        neutral = len(history) - positive - negative
        dominant_count = positive if weighted_score >= self.pressure_threshold else negative if weighted_score <= -self.pressure_threshold else 0
        persistence = dominant_count / len(history) if history else 0.0
        if weighted_score >= self.pressure_threshold:
            classification = "BUY_PRESSURE"
        elif weighted_score <= -self.pressure_threshold:
            classification = "SELL_PRESSURE"
        else:
            classification = "NEUTRAL"
        # Confidence-quality is not predictive confidence. It grades data depth,
        # persistence, and agreement among raw/top/weighted measures.
        depth_quality = min(len(bids), len(asks), requested_levels) / requested_levels
        directions = [score for score in (raw_score, top_score, weighted_score) if abs(score) > 1e-9]
        agreement = 1.0 if not directions or all(score * weighted_score > 0 for score in directions) else 0.0
        quality = round(100 * (0.5 * depth_quality + 0.3 * persistence + 0.2 * agreement), 2)
        return {
            "detector": "phase5_order_book_imbalance",
            "exchange": exchange,
            "symbol": symbol,
            "analyzed_at_ms": int(now * 1000),
            "levels_requested": requested_levels,
            "levels_used": {"bids": len(bids), "asks": len(asks)},
            "metrics": {
                "raw_bid_quantity": round(raw_bid_qty, 8),
                "raw_ask_quantity": round(raw_ask_qty, 8),
                "raw_imbalance": round(raw_score, 6),
                "top_of_book_imbalance": round(top_score, 6),
                "weighted_bid_quantity": round(bid_weighted, 8),
                "weighted_ask_quantity": round(ask_weighted, 8),
                "weighted_imbalance": round(weighted_score, 6),
                "pressure_score": round(weighted_score * 100, 2),
                "bid_wall_concentration": self._side_metrics(bids)["largest_level_concentration"],
                "ask_wall_concentration": self._side_metrics(asks)["largest_level_concentration"],
                "bid_side": self._side_metrics(bids),
                "ask_side": self._side_metrics(asks),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread": round(best_ask - best_bid, 10),
                "spread_pct": round((best_ask - best_bid) / best_bid * 100, 6),
            },
            "classification": classification,
            "threshold": self.pressure_threshold,
            "persistence": {
                "window_seconds": self.persistence_window_seconds,
                "samples": len(history),
                "buy_pressure_samples": positive,
                "sell_pressure_samples": negative,
                "neutral_samples": neutral,
                "current_pressure_persistence": round(persistence, 4),
                "pressure_change_from_previous": round(weighted_score - history[-2]["score"], 6) if len(history) > 1 else None,
                "pressure_change_per_second": round(pressure_change_per_second, 6) if pressure_change_per_second is not None else None,
                "pressure_acceleration_per_second2": round(pressure_acceleration_per_second2, 6) if pressure_acceleration_per_second2 is not None else None,
            },
            "quality": {
                "score": quality,
                "note": "Data-quality heuristic only; not a probability of a profitable trade.",
                "depth_coverage": round(depth_quality, 4),
                "raw_weighted_direction_agreement": bool(agreement),
            },
            "diagnostics": [
                "Large displayed liquidity can be canceled or spoofed.",
                "Pressure classification is not an entry signal.",
                "Detector refuses stale, unsynchronized, empty, crossed, or invalid books.",
            ],
        }

    def status(self) -> dict[str, Any]:
        return {
            "phase": 5,
            "engine": "order_book_imbalance_detector",
            "pressure_threshold": self.pressure_threshold,
            "history_size": self.history_size,
            "persistence_window_seconds": self.persistence_window_seconds,
            "max_book_age_seconds": self.max_book_age_seconds,
            "tracked_streams": len(self._history),
        }
