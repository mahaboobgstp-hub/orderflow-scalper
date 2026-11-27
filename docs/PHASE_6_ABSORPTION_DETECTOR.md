# Phase 6 — Absorption & Liquidity Behavior Engine

**Status:** Validation-branch corrections pending certification and deployment.  
**Mode:** Read-only analysis; no trading actions.

## Detection modules

- Aggressive buy/sell volume and trade count within the requested lookback.
- Net aggressive delta and absolute flow imbalance.
- Trade-side VWAP and spatial offset from the current midpoint.
- Side-normalized temporal midpoint progress from successive detector samples.
- Possible buy/sell absorption candidates: minimum sample count, aggressor-side volume share, and limited absolute temporal midpoint displacement (stalling).
- Flow weakening/stability heuristic based on volume in the recent versus earlier portion of the captured trade list.
- Top-five displayed bid/ask liquidity observation.
- Sample-to-sample top-five depth changes, labeled replenishment/depletion observations.
- Quality score describes data coverage only, not prediction probability.

## API

- `GET /api/absorption/status`
- `GET /api/absorption/{exchange}/{symbol}?lookback_seconds=15&limit=500`

The endpoint uses the Phase 3 normalized book and trade history. Supported exchange values are `binance`, `bybit`, and `delta`. It returns 404 if normalized book is unavailable and 422 when book validation fails.

## Direction and score interpretation

- Buy temporal progress is positive when the midpoint moves upward from the prior sample; sell temporal progress is positive when the midpoint moves downward. Negative values are preserved as adverse movement.
- The stall score decreases with the magnitude of side-normalized temporal midpoint displacement in either direction. Adverse movement is not automatically treated as absorption; flat movement maximizes the heuristic but does not prove passive liquidity.
- Spatial VWAP offsets are side-normalized: buy offset is positive when the current mid is above buy VWAP; sell offset is positive when sell VWAP is above the current mid.
- The current score is a heuristic with a 0.10% absolute-displacement scale and a minimum trade-count check. It penalizes favorable and adverse movement symmetrically. A high score is not a probability and is not a standalone trade instruction.

## Classification

- `POSSIBLE_BUY_ABSORPTION`: aggressive buys dominate the captured tape while the midpoint remains relatively stationary (small displacement in either direction). This may indicate passive sell liquidity absorbing buys.
- `POSSIBLE_SELL_ABSORPTION`: aggressive sells dominate the captured tape while the midpoint remains relatively stationary (small displacement in either direction). This may indicate passive buy liquidity absorbing sells.
- `MIXED_ABSORPTION`: both sides meet the candidate threshold.
- `NO_CLEAR_ABSORPTION`: no candidate meets the threshold/sample criteria.

These are research hypotheses, not reversal/entry signals.

## Limitations and safeguards

- Requires a synchronized, fresh, non-crossed book.
- Trade sides are accepted only as buy/sell; unknown sides are excluded.
- The unified engine's captured trades are capped history and are not guaranteed to fully represent the requested lookback.
- VWAP versus midpoint is spatial execution context, not true temporal price displacement from an interval start to end. It can be distorted by trade clustering, sampling, and side classification.
- Temporal midpoint movement is sampled on detector requests; request cadence can miss fast movement or produce incomparable intervals. It is not a continuous trade-time trajectory.
- A structural 1,000ms minimum interval is enforced for the temporal price-progress baseline. Rapid polls inside that interval cannot replace the baseline or score absorption. This is an anti-polling guard, not an empirically calibrated market threshold.
- Absorption scoring has no empirically calibrated absolute-volume/notional floor. Very small tape volumes may still qualify if the minimum trade count and volume-share tests pass.
- The 0.10% absolute-displacement scale and minimum-trade threshold are provisional and need market-based calibration across symbols, liquidity regimes, and noise.
- Liquidity changes are sampled on API requests. They are not linked to individual consumed orders, and aggregate depth increases alone do not prove replenishment.
- Flow weakening uses the timestamp-sorted captured trades but remains a heuristic; true rolling-time buckets are a future improvement.
- Quality score is evidence coverage only; no profitability prediction.
- Phase 3 synchronization limitations apply (notably Binance depth).

## Tests

Deterministic tests cover buy/sell candidates, favorable/adverse progress, both-direction threshold boundaries, stall-score behavior for adverse and flat movement, spatial VWAP signs, minimum trade count, invalid inputs, timestamp/lookback filtering, book rejection, sample-to-sample depth changes, and API output. Full backend and live exchange validation are still required for certification.
