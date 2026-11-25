# Phase 6 — Absorption & Liquidity Behavior Engine

**Status:** Implementation committed; runtime tests and live feed validation pending.  
**Mode:** Read-only analysis; no trading actions.

## Detection modules

- Aggressive buy/sell volume and trade count within the requested lookback.
- Net aggressive delta and absolute flow imbalance.
- Trade-side VWAP.
- Mid-price versus side VWAP price-progress estimate.
- Possible buy/sell absorption candidates: minimum sample count, dominant aggressor side, and limited VWAP-to-mid price progress.
- Flow weakening/stability heuristic based on volume in recent versus earlier portion of the captured trade list.
- Top-five displayed bid/ask liquidity observation.
- Sample-to-sample top-five depth changes, labeled replenishment/depletion observations.
- Quality score describes data coverage only, not prediction probability.

## API

- `GET /api/absorption/status`
- `GET /api/absorption/{exchange}/{symbol}?lookback_seconds=15&limit=500`

The endpoint uses the Phase 3 normalized book and trade history. Supported exchange values are `binance`, `bybit`, and `delta`. It returns 404 if normalized book is unavailable and 422 when book validation fails.

## Classification

- `POSSIBLE_BUY_ABSORPTION`: aggressive buys dominate the captured tape while estimated price progress is limited. This can indicate passive sell liquidity absorbing buys.
- `POSSIBLE_SELL_ABSORPTION`: aggressive sells dominate the tape while estimated price progress is limited. This can indicate passive buy liquidity absorbing sells.
- `MIXED_ABSORPTION`: both sides meet the candidate threshold.
- `NO_CLEAR_ABSORPTION`: no candidate meets the configured threshold/sample criteria.

These are research hypotheses, not reversal/entry signals.

## Limitations and safeguards

- Requires a synchronized, fresh, non-crossed book.
- Trade sides are accepted only as buy/sell; unknown sides are excluded.
- The unified engine's captured trades are capped history and are not guaranteed to fully represent the requested lookback.
- The current detector estimates price progress from trade-side VWAP against the current mid; this is a coarse proxy, not a true interval start/end price displacement.
- Liquidity changes are sampled on API requests. They are not yet linked to individual consumed orders, and aggregate depth increases alone do not prove replenishment.
- Flow weakening uses the currently captured trade list order and is a heuristic; true rolling-time buckets are a future improvement.
- Quality score is evidence coverage only; no profitability prediction.
- Phase 3 synchronization limitations apply (notably Binance depth).

## Tests added

`backend/tests/test_phase6_absorption_detector.py` contains deterministic tests for buy/sell candidates, minimum trade count, invalid book rejection, sample-to-sample depth change, and output fields. Full backend test execution and live exchange validation remain pending.
