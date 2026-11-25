# Phase 8 — Aggressive Trade Flow & Momentum Engine

**Status:** Implementation committed; runtime tests and live feed validation pending.  
**Mode:** Read-only market research.

## Metrics
- Aggressive buy/sell quantity, trade count, total volume, net delta, delta ratio and flow strength score (-100 to +100.
- Buy/sell VWAP, price progress versus trade-side VWAP, captured price movement over the lookback.
- Time-bucket trade volume and delta, last active bucket vs first active bucket activity change.
- Momentum activity classification: ACCELERATING, DECELERATING, STEADY, or INSUFFICIENT_BUCKETS.
- Flow classification: BUY_DOMINANT, SELL_DOMINANT, BALANCED, INSUFFICIENT_DATA.
- Divergence labels: BUY_FLOW_WITHOUT_UPWARD_PROGRESS or SELL_FLOW_WITHOUT_DOWNWARD_PROGRESS.

## API
- `GET /api/trade-flow/status`
- `GET /api/trade-flow/{exchange}/{symbol}?lookback_seconds=15&limit=500`

## Interpretive caution
- Buckets are derived from received timestamps and sparse trades may make acceleration comparisons unreliable.
- Flow-strength score represents net aggressive flow ratio, not a signal strength or win probability.
- Divergence may indicate absorption or opposing liquidity, but can also occur in noisy/lagging data.
- Trade-side correctness depends on adapter parsing.
- Requires synchronized, fresh, non-crossed order books. No trade signal or order execution.

## Tests
`backend/tests/test_phase8_trade_flow_momentum.py` includes dominant buy/sell, balanced flow, insufficient data, price-flow divergence and invalid-book rejection. Not executed in full backend runtime.
