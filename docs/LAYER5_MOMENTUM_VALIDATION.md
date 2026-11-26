# Layer 5 — Momentum Focused Validation Record

## Scope
Layer 5 now evaluates **price progress** independently from Layer 4's aggressive-trade delta. It consumes the Phase 8 trade-flow detector's `metrics.price_move_pct` and uses trade count/activity only to support confidence. L5 directional score does not use `delta_ratio` or `flow_strength_score`.

## Scoring
- Configurable scale: `momentum_price_move_scale_pct` (default 0.5 percentage points per ±100 score).
- Score: price move divided by scale, multiplied by 100, clamped to [-100, 100].
- Direction thresholds: the existing engine threshold of ±15.
- Availability requires valid price-progress data and at least `momentum_min_trades` (default 8).
- Invalid scale or minimum-trade config safely falls back to defaults.
- `momentum_activity` may support confidence, but does not set direction.

## Validation coverage
- L4/L5 same-direction cases.
- L4/L5 opposite-direction divergence case.
- Missing price-progress data.
- Insufficient trade count.
- Score clamping and direction thresholds.
- Configurable score scale.
- Invalid config fallbacks.
- End-to-end detector-generated rising/falling price progression; falling prices can produce L5 SELL even when aggressive trade delta is BUY.

## Certification boundary
Focused CI validates code behavior only. It does not certify predictive accuracy, market-data correctness, strategy profitability, or live trading. The feed's timestamps and trade-side correctness remain adapter-dependent. The engine remains paper-only.
