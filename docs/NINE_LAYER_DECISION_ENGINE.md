# Nine-Layer Decision Engine — Development Record

**Status:** Integrated into the autonomous PAPER runtime; feature-branch CI tests/build checks have passed. Strategy profitability and sustained live-feed validation remain unproven.
**Execution safety:** Paper simulator only. No live exchange order execution is called by this engine.

## Layers and evidence mapping

| Layer | Input source | Treatment |
|---|---|---|
| 1. Order-book imbalance | Phase 5 weighted imbalance | Leading directional evidence |
| 2. Absorption | Phase 6 buy/sell absorption hypotheses | Contrarian caution/evidence, direction mapping adjusted |
| 3. Liquidity zones / breakout | Phase 7 nearest trade-derived zone state | Breakout evidence only; rejection remains non-directional |
| 4. Aggressive order flow | Phase 8 delta ratio | Leading directional evidence |
| 5. Momentum | Phase 8 flow-strength score/activity | Mixed confirmation |
| 6. Spread and liquidity | Scanner spread and 24h quote volume | Hard quality gate; blocks entries |
| 7. Volatility / regime | Scanner ticker range and 24h price-change proxy | Provisional proxy; not candle regime |
| 8. Broader market context | BTC scanner 24h change proxy | Low-confidence context; unavailable when BTC absent |
| 9. Risk / execution | Position count, duplicate symbol, synchronized book, daily realized loss, consecutive losses, estimated open stop-risk | Hard entry gate and paper sizing |

## Decision policy
- Layer results are normalized to a bounded -100 to +100 score and report direction, confidence, availability, reasons and source data.
- Missing data is marked unavailable and is not counted as directional evidence.
- Weighted score and directional consensus must both meet configurable thresholds and minimum available directional-layer count.
- Decisions are BUY, SELL, HOLD, or REJECT.
- Spread/liquidity, stale/unsynchronized book, risk limits and duplicate-symbol checks are hard blockers.
- Position size is calculated by the Phase 10 risk sizing engine from account equity and proposed stop distance.
- Paper orders are routed only to the existing simulator, with fixed stop-loss plus trailing stop-loss and trailing take-profit settings from operator config.
- Decisions/layer payloads and candidate signals are persisted through the repository when decision state changes.
- Diagnostics are exposed at `GET /api/decision-engine/status`.

## Known integration limitations (must be addressed in later tasks)
- The Binance depth stream currently lacks REST snapshot bridging and marks its book unsynchronized, so Layer 1 and dependent book-based layers will remain unavailable for that feed until snapshot synchronization is implemented.
- Detector availability depends on a symbol actually having synchronized live book and trades in the unified engine.
- Layer 7/8 use ticker proxies and are not validated candle-based regime/context.
- Daily loss and consecutive loss gates currently use in-memory simulator trade history; durable recovery and edge cases require later testing.
- This record documents code/CI validation only; it does not imply strategy profitability, sustained live-feed quality, or production deployment validation.
