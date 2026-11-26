# Phase F — Absorption & Liquidity Behavior Hardening

## Scope
Phase F extends the existing Phase 6 absorption detector and Phase 7 trade-derived liquidity-zone detector. It does not duplicate them or turn research classifications into standalone order instructions.

## Architecture audit (Phase F Step 1)
- Absorption detector: `backend/app/services/absorption_detector.py`; API route and runtime integration already exist.
- Liquidity-zone detector: `backend/app/services/liquidity_zone_detector.py`; API route and nine-layer integration already exist.
- Nine-layer decision engine consumes absorption as Layer 2 and liquidity-zone evidence as Layer 3.
- Unified market data supplies synchronized books and recent public trades.
- Both detectors refuse unsynchronized, stale, or integrity-failing books.
- Existing Phase 6/7 unit and API tests provide a baseline.

## Completed hardening in Phase F
- Added explicit interpretation metadata that clarifies absorption side versus passive liquidity side.
- Aggressive buy absorption is labeled bearish caution (passive sellers may be absorbing); aggressive sell absorption is labeled bullish caution (passive buyers may be absorbing). Both remain hypotheses and never standalone signals.
- Added trade notional metrics (price × quantity) for aggressive buy, aggressive sell, and total captured trades.
- Quality score now counts the temporal baseline only if it is within the detector's requested lookback, instead of awarding baseline points to any historical sample.
- Added regression tests for directional interpretation, notional metrics, and stale-baseline quality.

## Remaining Phase F validation gates
- Automated CI must pass after the Phase F branch changes.
- Existing Phase 6 and Phase 7 test suites must remain green.
- Nine-layer integration must remain green; no new detector may bypass Layer 9 risk/execution.
- Confirm paper-only behavior and no live-execution enablement.
- Manual market observation/replay remains a separate certification step and cannot be claimed from unit tests alone.

## Limitations
- Liquidity replenishment is sampled on analysis calls, not full event-level order-book tracking.
- Price clusters are inferred from captured public trades; they are not exchange liquidity heatmaps or verified resting-order zones.
- Confidence/quality is an evidence-quality heuristic, not a win probability.
- Detector outputs do not establish profitability.
