# Phase 4 — Coin Scanner & Market Selection Engine

## Implemented
- Binance USD-M perpetual USDT contract universe via exchangeInfo.
- 24h ticker metrics: quote volume, trades count, price change, high/low range, bid/ask spread proxy.
- Configurable minimum volume, maximum spread, daily range bounds.
- Suitability ranking heuristic with liquidity, spread, volatility/range, trade activity, 24h momentum components.
- 5-minute quote-volume acceleration ratio for bounded shortlist (maximum 50 symbols, default 30); ratio is recent closed bar quote volume / preceding closed bar quote volume.
- Candidate/reject reasons, ranked output, optional rejected-market inclusion.
- FastAPI scan endpoint: GET /api/scanner/coins?limit=20&include_rejected=false
- No order placement, no signal generation, no strategy conclusions.

## Caveats
- Initial implementation uses Binance USD-M Futures public REST market data only. Multi-exchange candidate universe can be expanded in later phases.
- 24h ticker spread is a best bid/ask estimate, not depth/slippage analysis; Phase 10/11 will add deeper risk and execution-quality checks.
- 5m acceleration is only computed for the ranked shortlist, with a configurable bounded request count. It compares closed 5m bars and is not guaranteed for every coin.
- Ranking weights are heuristic and not validated predictive probabilities. Thresholds are configurable in the service constructor.
- Runtime API request, exchange rate-limit behavior, and tests have not yet been executed in a full backend environment.

## Tests
Unit tests cover helper clamping/numeric parsing and shortlist configuration bounds.
