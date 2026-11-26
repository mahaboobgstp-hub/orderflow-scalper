# Layer 7 — Volatility Regime Validation

## Scope
Focused software validation of the Phase 9 read-only volatility/regime classifier and its dummy candle adapter.

## Data boundary
The provider emits deterministic mock OHLCV values marked `DUMMY`, `is_live=false`. No real exchange candles are used in this suite and no trading orders are produced.

## Classification
Trend: UPTREND / DOWNTREND / RANGING.
Volatility state: EXPANSION / COMPRESSION / NORMAL.
Composite: TRENDING_VOLATILE / TRENDING_LOW_VOL / RANGE_VOLATILE / RANGE_COMPRESSION / MIXED_OR_NORMAL.
A volatility spike is a heuristic flag based on latest candle range compared with baseline average range.

## Focused tests
Dummy-provider metadata and candle shape; schema and diagnostics; rising/falling/ranging price paths; expansion and compression behavior; spike flag; malformed/invalid OHLC candles; volume sanitization; minimum-history behavior; bounded periods and constructor history limits; malformed periods; metric finiteness.

## Certification limitations
Passing software tests do not prove volatility classifications are accurate for live markets or profitable. Thresholds remain heuristics. Live-data, calibration, backtesting and predictive-value testing are not included.

## Nine-layer integration boundary
The standalone candle classifier is exposed through Phase 9 market-context endpoints and is not directly wired into the live nine-layer decision-engine aggregation. The nine-layer engine's Layer 7 currently uses the scanner's 24-hour range and price-change proxy to score directional context. Focused tests cover this proxy separately. This certification does not claim full candle-classifier integration into the decision runtime.
