# Phase D — Trade Management Engine

**Status:** Development implemented; CI verification pending.  
**Mode:** Paper-only/advisory. The endpoint calculates a management plan and never places, modifies, or closes orders.

## Capabilities

- Initial protective stop using configured entry-relative percentage.
- Break-even protection activates after a favorable move threshold and adds a small configurable offset.
- Trailing stop-loss follows the best favorable price only after the position has moved favorably; it cannot loosen the calculated protective stop.
- Trailing take-profit activates after a favorable threshold and trails the best favorable extreme.
- Trend-extension mode can suppress the optional time-based exit while trend score is strong and price move is favorable.
- Trend weakening exit advisory for weak trend scores when price is not favorable.
- Optional maximum holding-time advisory.
- Returns the tracked favorable extreme (best_price) for caller-side persistence, plus exit reason and explainability notes.

## Default parameters

| Setting | Default |
|---|---:|
| Initial stop | 1.00% |
| Break-even trigger | 0.80% |
| Break-even offset | 0.05% |
| Trailing stop | 0.75% |
| Trailing take-profit activation | 1.20% |
| Trailing take-profit distance | 0.50% |
| Trend extension threshold | 65 / 100 |
| Weak-trend exit threshold | 25 / 100 |
| Maximum hold | disabled |

Defaults are provisional engineering parameters and are not validated trading recommendations or profitability claims.

## API

- GET /api/trade-management/status: configuration and feature list.
- POST /api/trade-management/evaluate: deterministic management evaluation.

Example request:
```json
{
  "position": {
    "symbol": "BTCUSDT",
    "side": "long",
    "entry_price": 100,
    "best_price": 101,
    "opened_at_seconds": 0
  },
  "market": {
    "mark_price": 101,
    "trend_score": 70
  },
  "config": {},
  "now_seconds": 120
}
```

The response includes best_price, stop levels, activation flags, trend-extension flag, exit_action, exit_reason, and management notes. The caller must persist the returned best price if it wants trailing logic to retain the favorable extreme between evaluations.

## Tests

Focused unit coverage includes long/short directional behavior, stop exit, trailing take-profit exit, trend weakening, trend-extension time-exit suppression, validation, and favorable-extreme tracking.
