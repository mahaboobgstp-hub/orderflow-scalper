# Phase 10 — Risk Management & Position Sizing

## APIs
- `GET /api/risk/status` — defaults and disclaimer
- `POST /api/risk/position-size` — risk-budget position size based on entry/stop
- `POST /api/risk/portfolio-check` — advisory portfolio guard evaluation

## Default research configuration
Risk per trade: 0.5% equity; max daily loss 2%; max total open risk 3%; max notional 25% equity; max leverage 5x; max concurrent positions 3; stop after 3 consecutive losses.

## Calculation
Risk budget = equity × risk percentage. Position quantity = risk budget / absolute entry-stop distance, then capped by notional limit. Margin estimate = notional / leverage. Portfolio guard flags daily-loss, total-open-risk, max-positions, and consecutive-loss limits.

## Safety
This is calculation-only/advisory. It does not submit orders or enforce limits in execution. Fees, funding, slippage, liquidation, lot-size and contract-specific multipliers are not yet included. The defaults are development starting points, not recommendations. Stop execution is not guaranteed.

## Validation
Tests added; not executed in the repository runtime.
