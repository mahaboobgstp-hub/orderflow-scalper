# Layer 9 — Risk & Execution Gate Validation

## Scope
Validates the nine-layer engine's final risk gate, risk sizing and portfolio guard behavior. Paper-only runtime; no exchange orders are submitted.

## Checks
- Explicit permission is required (strict boolean true).
- Empty blockers required for gate pass.
- Missing, false, non-boolean, or malformed permission inputs fail closed.
- Malformed blocker containers fail closed.
- All known runtime/session blockers reject.
- Layer 9 is non-directional.
- Position sizing input validation and portfolio guard limits.
- Gate integration preserves REJECT/entry_eligible false and paper-only restrictions.

## Findings fixed
- Risk permission previously used Python truthiness, which could accept values such as strings or integer 1 as allowed. It now requires literal boolean true.
- A malformed blocker container previously could be converted into a list of characters or be mishandled; it now fails closed with an explicit blocker.

## Limits
Software validation only. No certification of actual stop fills, slippage, liquidation protection, durable risk-state recovery, or trading profitability. Exchange order service validation is separate and does not mean live execution is enabled.
