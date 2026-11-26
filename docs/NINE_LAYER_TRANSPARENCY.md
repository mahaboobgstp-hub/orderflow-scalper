# Nine-Layer Transparency Contract

This document describes the backend decision record fields and how the Web Live Activity trace presents them. The same field contract is intended to be usable by the Android remote shell.

## Decision record

Each runtime decision includes its symbol, exchange, decision (BUY, SELL, HOLD, or REJECT), side, weighted score, consensus ratio, directional-layer count, minimum-layer requirement, entry eligibility, the layer map, and paper execution details. The runtime stamps each evaluated decision with **evaluated_at** (Unix seconds); the UI uses the last scan time only as a fallback for older records without an individual timestamp.

## Layer record contract

Each layer record has these fields:

| Field | Meaning |
|---|---|
| layer | Exact key identifying the layer |
| score | Bounded directional score, -100 to +100; may be null when unavailable |
| direction | BUY, SELL, NEUTRAL, or BLOCK |
| confidence | Detector/engine confidence scale, 0–100; not a probability of profit |
| available | Whether usable evidence was produced; a risk layer can be available and still block |
| reasons | Human-readable explanation supplied by the engine |
| data | Raw/derived evidence; may be an object or a list (for example, liquidity-zone evidence) |

The UI renders all nine named cards. A missing key is shown as **MISSING**, counted separately from a layer that exists but reports unavailable. Raw evidence is expandable; empty evidence is not fabricated.

## Layer interpretation

| Layer | Current implementation |
|---|---|
| 1. Order Book Imbalance | Weighted bid/ask imbalance detector output normalized to directional score |
| 2. Absorption | Difference between sell- and buy-absorption hypotheses; treated as caution/evidence, not a standalone trade instruction |
| 3. Liquidity Breakout | Trade-derived liquidity-zone state; breakout up/down receives directional evidence, possible rejection remains neutral; raw zone evidence is a list |
| 4. Aggressive Order Flow | Aggressive trade delta ratio normalized to score |
| 5. Momentum | Price progress scaled and capped; requires enough trades; calculated independently of Layer 4 delta |
| 6. Spread & Liquidity | Hard quality gate using spread and 24-hour quote-volume thresholds; missing/invalid inputs fail closed |
| 7. Volatility Regime | Uses 24-hour range and price-change ticker proxy; provisional, not candle-based volatility classification |
| 8. Broader Market Context | BTC 24-hour ticker-change proxy supplied by runtime; unavailable if broader ticker context is missing |
| 9. Risk & Execution Gate | Hard permission gate from portfolio/session risk. Passing is neutral, failing is BLOCK; it is not a directional vote |

## Aggregate decision and gates

- Aggregate score is a weighted average of available directional evidence from Layers 1–8; Layer 9 is excluded from directional voting.
- Consensus ratio describes the relative weight of the stronger side, not a calibrated probability.
- **entry_eligible** means the nine-layer decision engine produced BUY/SELL. It is **not** equivalent to permission from a controlled paper session.
- The trace separately displays the controlled-session gate, blockers, and the actual paper-execution outcome.
- Missing eligibility is displayed as **UNKNOWN**, not as an inferred NO.

## Backend record traceability

The runtime now attaches persistence metadata to each recent decision:

- **decision_persistence**: PERSISTED, UNCHANGED, UNCONFIRMED, ERROR, or NOT_CONFIGURED, with the returned decision_logs record ID when available.
- **signal_persistence**: separate signal-record status and ID for BUY/SELL decisions; NOT_APPLICABLE for non-directional decisions.

An unchanged signature reuses the cached returned ID. A decision insert exception is not cached, allowing the next scan to retry. If the backend returns no record ID, the trace does not claim persistence was confirmed. Signal persistence failures are reported separately from a successfully persisted decision.

## Limitations / certification notes

- Confidence values are detector/engine scales, not statistically calibrated probabilities or performance guarantees.
- Layers 7 and 8 use ticker proxies, not validated candle-derived regime models.
- Evidence payload shape is intentionally heterogeneous (objects and lists); clients must preserve and display it as JSON rather than assume one fixed nested schema.
- A decision record ID is available only when the persistence API returns it. Older trace records may lack persistence metadata.
- The UI build and backend tests are CI-validated on the feature branch; deployment may be blocked by the current Vercel build/deployment rate limit.
- This transparency layer does not activate paper sessions, place exchange orders, or change execution safety configuration.
