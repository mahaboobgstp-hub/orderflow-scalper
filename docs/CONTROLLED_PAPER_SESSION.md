# Task 5 — Controlled Paper-Session Development

**Status:** Framework and lifecycle controls implemented. Validation execution intentionally deferred.

## Session controls
- Session is opt-in; controller starts disabled and no paper session begins automatically.
- Explicit API start/pause/resume/stop lifecycle.
- Session controls cap trade count, concurrent positions, session loss, per-trade risk, leverage and session duration.
- Direction permissions can be toggled (long/short).
- Synchronized order book is required by default.
- Auto-pause on time, loss, or trade-count limits.
- Entry attempts are gated by active session; session metrics record simulated entries and exits.
- Config values are clamped to conservative supported bounds.
- All controls and records explicitly identify PAPER_ONLY; live exchange execution is never enabled.

## API
- GET `/api/paper/validation/status`
- POST `/api/paper/validation/start`
- POST `/api/paper/validation/pause`
- POST `/api/paper/validation/resume`
- POST `/api/paper/validation/stop`

Starting a session activates the controlled-session gate; the autonomous runtime must also be running to generate paper entries. The controller is not auto-started.

## Planned combined validation scenarios (not executed)
1. Controller disabled: entry blocked.
2. Session start: session becomes ACTIVE and records starting equity.
3. Pause/resume/stop lifecycle: state transitions and entry eligibility behave as expected.
4. Session trade-count limit: entries stop at the configured maximum and auto-pause.
5. Session duration: timed auto-pause.
6. Session loss threshold: auto-pause when loss limit reached.
7. Long-only / short-only permissions.
8. Unsynchronized or missing book rejection.
9. Concurrent position cap and duplicate-symbol gate.
10. Risk sizing capped by per-session risk and leverage controls.
11. Entry/exit metrics record paper-only events.
12. Existing paper portfolio/account metrics remain distinct from session metrics.

## Session summary metrics
Controller tracks trade entries, exits, wins/losses, realized P&L, elapsed duration, pause reason and recent lifecycle events. Detailed performance analysis and reconciliation are reserved for the combined validation stage.

## Safety note
This development framework does not create real exchange orders, does not use live execution APIs, and does not prove strategy profitability. Testing and runtime validation are deferred by operator instruction until the planned development tasks are complete.
