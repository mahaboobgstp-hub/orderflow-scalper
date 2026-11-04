"""
OrderFlow Scalper - Feature Engine

Converts market data into numeric features for research and model training.

This module:
- Does not place orders.
- Does not train a model.
- Does not use future data.
- Returns None for unavailable features instead of inventing values.
"""

from __future__ import annotations

from math import log
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


Number = Optional[float]


def _safe_float(value: Any) -> Optional[float]:
    """Convert a value to a finite float, otherwise return None."""
    try:
        result = float(value)
        if result != result or result in (float("inf"), float("-inf")):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _safe_divide(
    numerator: Optional[float],
    denominator: Optional[float],
) -> Optional[float]:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _stddev(values: Sequence[float]) -> Optional[float]:
    if len(values) < 2:
        return None

    average = sum(values) / len(values)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return variance ** 0.5


def _log_returns(prices: Sequence[float]) -> List[float]:
    returns: List[float] = []

    for previous, current in zip(prices[:-1], prices[1:]):
        if previous > 0 and current > 0:
            returns.append(log(current / previous))

    return returns


def _normalise_side(
    levels: Iterable[Sequence[Any]],
) -> List[Tuple[float, float]]:
    """
    Convert order-book levels into (price, quantity).

    Expected level format:
        [["price", "quantity"], ...]
    """
    result: List[Tuple[float, float]] = []

    for level in levels:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue

        price = _safe_float(level[0])
        quantity = _safe_float(level[1])

        if price is None or quantity is None:
            continue

        if price <= 0 or quantity < 0:
            continue

        result.append((price, quantity))

    return result


def _depth_quantity(
    levels: Sequence[Tuple[float, float]],
    count: int,
) -> float:
    return sum(quantity for _, quantity in levels[:count])


def _weighted_average_price(
    levels: Sequence[Tuple[float, float]],
    count: int,
) -> Optional[float]:
    selected = levels[:count]

    total_quantity = sum(quantity for _, quantity in selected)
    if total_quantity <= 0:
        return None

    total_value = sum(price * quantity for price, quantity in selected)
    return total_value / total_quantity


def _trade_flow(
    trades: Sequence[Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    """
    Expected trade fields:
        price
        quantity
        is_buyer_maker

    Binance convention:
        is_buyer_maker=True means the buyer was passive,
        so the seller was the aggressor.
    """
    buy_volume = 0.0
    sell_volume = 0.0
    total_volume = 0.0
    trade_count = 0

    for trade in trades:
        price = _safe_float(trade.get("price"))
        quantity = _safe_float(
            trade.get("quantity", trade.get("qty"))
        )

        if price is None or quantity is None:
            continue

        if price <= 0 or quantity <= 0:
            continue

        total_volume += quantity
        trade_count += 1

        buyer_maker = trade.get("is_buyer_maker")

        if buyer_maker is True:
            sell_volume += quantity
        elif buyer_maker is False:
            buy_volume += quantity

    total_aggressor_volume = buy_volume + sell_volume

    return {
        "trade_count": float(trade_count),
        "buy_aggressor_volume": buy_volume,
        "sell_aggressor_volume": sell_volume,
        "total_trade_volume": total_volume,
        "trade_flow_imbalance": _safe_divide(
            buy_volume - sell_volume,
            total_aggressor_volume,
        ),
    }


def build_features(
    *,
    symbol: str,
    timestamp_ms: int,
    bids: Sequence[Sequence[Any]],
    asks: Sequence[Sequence[Any]],
    recent_trades: Sequence[Dict[str, Any]],
    candle_closes: Sequence[Any],
    candle_volumes: Optional[Sequence[Any]] = None,
    mark_price: Any = None,
    funding_rate: Any = None,
) -> Dict[str, Any]:
    """
    Build a feature row from a point-in-time market snapshot.

    candle_closes and candle_volumes must be ordered oldest to newest.
    Only completed candles should be passed for model training.
    """

    bid_levels = _normalise_side(bids)
    ask_levels = _normalise_side(asks)

    # Correct order-book ordering.
    bid_levels.sort(key=lambda item: item[0], reverse=True)
    ask_levels.sort(key=lambda item: item[0])

    best_bid = bid_levels[0][0] if bid_levels else None
    best_ask = ask_levels[0][0] if ask_levels else None

    mid_price = None
    spread = None
    spread_bps = None

    if best_bid is not None and best_ask is not None:
        if best_ask >= best_bid:
            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid

            if mid_price > 0:
                spread_bps = (spread / mid_price) * 10000

    bid_depth_5 = _depth_quantity(bid_levels, 5)
    ask_depth_5 = _depth_quantity(ask_levels, 5)

    bid_depth_10 = _depth_quantity(bid_levels, 10)
    ask_depth_10 = _depth_quantity(ask_levels, 10)

    total_depth_5 = bid_depth_5 + ask_depth_5
    total_depth_10 = bid_depth_10 + ask_depth_10

    depth_imbalance_5 = _safe_divide(
        bid_depth_5 - ask_depth_5,
        total_depth_5,
    )

    depth_imbalance_10 = _safe_divide(
        bid_depth_10 - ask_depth_10,
        total_depth_10,
    )

    bid_weighted_price_5 = _weighted_average_price(bid_levels, 5)
    ask_weighted_price_5 = _weighted_average_price(ask_levels, 5)

    microprice = None

    if (
        best_bid is not None
        and best_ask is not None
        and bid_levels
        and ask_levels
    ):
        best_bid_quantity = bid_levels[0][1]
        best_ask_quantity = ask_levels[0][1]
        total_best_quantity = best_bid_quantity + best_ask_quantity

        if total_best_quantity > 0:
            microprice = (
                best_ask * best_bid_quantity
                + best_bid * best_ask_quantity
            ) / total_best_quantity

    closes: List[float] = []

    for value in candle_closes:
        number = _safe_float(value)
        if number is not None and number > 0:
            closes.append(number)

    returns = _log_returns(closes)

    return_1 = None
    return_3 = None
    return_5 = None
    return_10 = None

    if len(closes) >= 2:
        return_1 = (closes[-1] / closes[-2]) - 1

    if len(closes) >= 4:
        return_3 = (closes[-1] / closes[-4]) - 1

    if len(closes) >= 6:
        return_5 = (closes[-1] / closes[-6]) - 1

    if len(closes) >= 11:
        return_10 = (closes[-1] / closes[-11]) - 1

    volatility_5 = _stddev(returns[-5:])
    volatility_10 = _stddev(returns[-10:])
    volatility_20 = _stddev(returns[-20:])

    volume_values: List[float] = []

    if candle_volumes:
        for value in candle_volumes:
            number = _safe_float(value)
            if number is not None and number >= 0:
                volume_values.append(number)

    latest_volume = volume_values[-1] if volume_values else None
    average_volume_20 = _mean(volume_values[-20:])

    volume_ratio_20 = _safe_divide(
        latest_volume,
        average_volume_20,
    )

    trade_features = _trade_flow(recent_trades)

    mark = _safe_float(mark_price)
    funding = _safe_float(funding_rate)

    return {
        "symbol": symbol.upper(),
        "timestamp_ms": int(timestamp_ms),

        # Price and spread
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid_price": mid_price,
        "spread": spread,
        "spread_bps": spread_bps,
        "microprice": microprice,

        # Order-book liquidity
        "bid_depth_5": bid_depth_5,
        "ask_depth_5": ask_depth_5,
        "bid_depth_10": bid_depth_10,
        "ask_depth_10": ask_depth_10,
        "depth_imbalance_5": depth_imbalance_5,
        "depth_imbalance_10": depth_imbalance_10,
        "bid_weighted_price_5": bid_weighted_price_5,
        "ask_weighted_price_5": ask_weighted_price_5,

        # Candle momentum
        "return_1": return_1,
        "return_3": return_3,
        "return_5": return_5,
        "return_10": return_10,

        # Volatility
        "volatility_5": volatility_5,
        "volatility_10": volatility_10,
        "volatility_20": volatility_20,

        # Volume
        "latest_candle_volume": latest_volume,
        "average_volume_20": average_volume_20,
        "volume_ratio_20": volume_ratio_20,

        # Trade flow
        **trade_features,

        # Futures context
        "mark_price": mark,
        "funding_rate": funding,
  }
