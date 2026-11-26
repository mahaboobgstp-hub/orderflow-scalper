# Layer 6 — Spread & Liquidity Validation

## Scope
Layer 6 evaluates whether a market is sufficiently tradable based on the current quoted spread and 24-hour quote volume. It is a strict paper-mode gate, not directional evidence.

## Inputs and units
- `spread_pct`: percentage points, consistent with Phase 4 CoinMarketScanner output.
- `quote_volume_24h`: quote currency volume, expected USD/USDT-denominated value for the scanner's USDT futures universe.
- Defaults: maximum spread 0.12%; minimum 24-hour quote volume 1,000,000.
- Both thresholds are configurable.

## Behavior
- Pass: spread and volume are valid and both meet thresholds; L6 is NEUTRAL, score +60.
- Excess spread: BLOCK, score -100.
- Low volume: BLOCK, score -60.
- Missing, negative, or invalid inputs: BLOCK (fail-closed), score -80 where inputs cannot be classified as a specific threshold failure.
- A BLOCK prevents an overall decision from becoming BUY/SELL.

## Test coverage
Valid pass, too-wide spread, low volume, exact threshold boundaries, config overrides, invalid threshold fallback, missing values, malformed values, negative values, NaN/Infinity.

## Certification boundary
Focused CI validates the gate behavior and integration only. It does not establish actual market execution costs, order-book depth, slippage, fills, or profitability. The spread is ticker bid/ask spread; 24h quote volume is a liquidity proxy, not immediate executable depth.
