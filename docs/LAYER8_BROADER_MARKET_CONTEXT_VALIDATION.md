# Layer 8 — Broader Market Context Focused Validation

## Scope
Layer 8 consumes externally supplied `inputs["broader_context"]` as a dictionary with a numeric `score`, optional `confidence`, `reasons`, and contextual `data`. It does not independently fetch broader-market data or validate source freshness/identity.

## Focused checks
- Score direction threshold, neutral band, and clamping
- Missing, malformed, NaN, and infinite scores marked unavailable
- Confidence sanitation/bounds
- Context reasons and data preservation
- No trade entry from Layer 8 alone
- Paper-only output and live execution disabled
- Context independence from symbol when no other directional layers exist

## Limitations
This certification covers software handling of supplied context only. It does not certify that a BTC/market context provider is connected, current, accurate, resilient, or predictive. No market-performance or profitability claims are made.
