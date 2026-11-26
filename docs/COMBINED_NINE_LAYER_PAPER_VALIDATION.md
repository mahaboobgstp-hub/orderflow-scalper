# Combined Nine-Layer Integration & Controlled Paper Validation

## Scope
This validation combines the nine-layer decision engine, controlled-session gate, autonomous paper runtime, and paper simulator. All order execution is simulated. Live exchange order execution is explicitly disabled.

## Test coverage
- Nine layer outputs and paper-only response safety.
- Strong synthetic BUY consensus.
- Directional conflict between layers.
- Missing or non-finite critical L1/L4 inputs fail closed.
- Layer 6 spread/volume blocks and missing-data rejection.
- Layer 9 risk permission/blocker enforcement.
- Layer 5 momentum remains price-progress based and independent from L4 aggressive delta.
- Neutral evidence resolves to HOLD.
- Invalid layer-weight overrides are ignored.
- Controlled session disabled-by-default, lifecycle, synchronized-book requirement, long/short permissions, open-position cap, trade-count cap, loss/time auto-pause, metrics and configuration clamping.
- Runtime tests: inactive controlled session blocks paper entry; active session permits simulated-only order; session position cap blocks entry.
- Existing paper engine tests cover fees/margin, duplicate positions, stop-loss/take-profit, trailing stop-loss, trailing take-profit, management changes, long/short P&L and reset.
- Existing persistence tests cover account-state recovery and lifecycle persistence calls.

## Guardrail corrections discovered during combined testing
1. The decision engine now rejects entries when either critical directional input (L1 order-book imbalance or L4 aggressive flow) is unavailable or invalid.
2. Controlled paper-session gating now enforces its own maximum open-position count using the actual simulator position count.
3. Paused sessions no longer incorrectly label every pause as a session-time-limit blocker.
4. Tests were corrected to use realistic timestamps and isolated mock instances; the L6 focused test supplies critical L1/L4 inputs so it measures L6 behavior separately.

## Certification status
- Combined synthetic decision integration: CI validated.
- Controlled paper-session lifecycle and guardrails: CI validated in the combined workflow.
- Runtime-to-paper execution boundary: tested in controlled CI.
- Paper simulator fixed and trailing management: covered by backend regression tests.
- Full backend regression suite: passed in GitHub Actions (388 tests, 15 subtests).
- Live exchange stream synchronization and sustained runtime stability: still require separate operational observation.
- Real-market signal quality and profitability: not certified.

Synthetic fixtures validate software behavior, not market accuracy. No live orders are enabled.
