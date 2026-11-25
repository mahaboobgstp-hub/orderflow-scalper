# Phase 12 — Advanced Paper Position Management

Phase 12 extends Phase 11 paper-only positions with protective and profit-locking exits. All exits are evaluated when a mark price is submitted to the simulator.

## Controls
- Fixed stop loss (absolute trigger price)
- Fixed take profit (absolute trigger price)
- Trailing stop loss (TSL): trails the favorable extreme by a configured percentage from entry onward.
- Trailing take profit (TTP): activates after a configured favorable percentage move, then follows the favorable extreme with a trail percentage and exits on retracement.

Longs track the highest observed mark; shorts track the lowest observed mark. Fixed SL/TP and trailing exits are checked on each mark. If multiple exit conditions are met on the same mark, precedence is fixed SL, fixed TP, TSL, then TTP.

## API
- `POST /api/paper/orders`: optional management fields may be provided at entry.
- `POST /api/paper/manage/{symbol}`: update management settings on an open paper position.
- `POST /api/paper/mark-price`: updates price, calculates trailing thresholds, and automatically closes when an exit condition is reached.
- `POST /api/paper/close/{symbol}`: manual paper close remains available.

## Entry fields
`stop_loss_price`, `take_profit_price`, `tsl_enabled`, `tsl_distance_pct`, `ttp_enabled`, `ttp_activation_pct`, `ttp_trail_pct`.

## Validation and limitations
- Stop-loss and take-profit must be on the correct side of entry for long/short.
- Trailing percentages must be greater than 0 and less than 100.
- TSL enabled requires distance; TTP enabled requires activation and trail percentages.
- In-memory state is lost on restart.
- Exit checks are mark-price based; no tick-level replay, slippage, gaps, latency, exchange triggers, liquidation simulation, or guaranteed fill price.
- This is simulation only; no real exchange order calls.
- Tests authored but not run in repository environment.
