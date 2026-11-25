# Phase 7 — Liquidity Zone & Breakout Detector

**Status:** Implementation committed; runtime API tests and exchange feed validation pending.  
**Mode:** Read-only research.

## What it estimates
- Trade-price clusters across a configurable lookback, forming inferred liquidity/interaction zones.
- Zone boundaries, center, trade volume observed within cluster, interaction count, last observed interaction.
- Current mid-price position relative to each zone and percent distance.
- Current top-five displayed bid/ask quantity reference levels (not historical heatmap).
- States: `APPROACHING`, `IN_ZONE`, `BREAKOUT_UP`, `BREAKOUT_DOWN`, `POSSIBLE_REJECTION`, and `ZONE_RETEST_OR_REENTRY`.

## How interaction is interpreted
- **Approaching:** price is close to a zone boundary, but not within it.
- **Inside:** price trades inside the zone.
- **Break:** current mid-price is outside the zone plus/minus a configurable buffer. This is not candle-close confirmation.
- **Possible rejection:** captured trade sequence touches the cluster then subsequently moves away. Heuristic only.
- **Reset / re-entry:** price returns inside a previously observed breakout/rejection zone. The API labels this `ZONE_RETEST_OR_REENTRY`; it is not proof the zone has been renewed.

## API
- `GET /api/liquidity-zones/status`
- `GET /api/liquidity-zones/{exchange}/{symbol}?lookback_seconds=300&limit=500`

## Caveats
- Zones are trade-price clusters, not exchange-provided liquidity heatmaps, candle swing levels, or resting order maps.
- Trades and order-book snapshots are captured public feed data; completeness varies by exchange and symbol.
- Touch count counts trade records within a cluster, not independently verified tests.
- Break/rejection classifications require synchronized, fresh order books; Binance synchronization limitations from Phase 3 still apply.
- A robust rejection/breakout confirmation layer using candle closes, time spent outside, sequence tracking, and volume thresholding is a future refinement.
- No trade signals or execution decisions are generated.

## Tests added
`backend/tests/test_phase7_liquidity_zone_detector.py` includes zone formation, breakout state, re-entry/reset, stale/unsynchronized rejection, and empty-history cases. Full test suite and live validation have not been executed.
