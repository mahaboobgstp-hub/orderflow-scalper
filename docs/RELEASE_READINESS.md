# OrderFlow Scalper — Release Readiness Snapshot

**Audit date:** 26 November 2026  
**Target:** Android app + observable, controlled paper/demo session  
**Execution safety:** PAPER/DEMO only. Real exchange order execution must remain disabled.

## Highest-priority release blocker

The Android branch still contains a **placeholder research dashboard** with hard-coded illustrative order-book values and explicitly says its backend is not connected. The existing APK is a shell artifact—not the monitoring app needed to watch live feeds, scanner decisions, all nine layers, risk gates, positions, stops, trailing exits, and paper P&L. The mobile UI must be integrated with the validated feature code and deployed backend before device demo.

## Current branch/PR audit

| PR | Head / base | Status | CI evidence |
|---|---|---|---|
| #1 Layer 1 snapshot bridge | `fix/layer1-binance-snapshot-bridge` → `main` | Open, non-draft; separate feed fix | Focused sync checks passed; backend checks failed on this head |
| #8 Transparency/feed/runtime bundle | `feature/observability-trader-transparency` → `main` | Open, non-draft; 53 commits | Previous head had 5 green checks; **feed freshness hardening passed all five checks on code commit `85b3941f330989b43fcda4db3c820d97de3fee16`**; the later release-checklist document commit is docs-only and may trigger a fresh CI run |
| #9 Central Risk Engine | `feature/phase-e-risk-engine` → `main` | Open, draft; 75 commits | 5 checks green (backend, Layer 9, combined paper, frontend build, infrastructure) |
| #10 Absorption/liquidity hardening | `feature/phase-f-absorption-liquidity` → #9 branch | Open, draft; 8 commits | 2 checks green (backend and focused Layer 2) |
| #7 pytest CI fix | `fix/infra-pytest-dependency-20261126` → `main` | Open, draft | Backend infrastructure check green |
| #2–#6 validation/fix PRs | Multiple separate `main` branches | Open and overlapping | Several validation branches are green; branch overlap requires consolidation |

**Do not merge the stack yet.** #8 and #9 both target `main`; #10 is stacked on #9; separate Layer 1/2 fixes and validation PRs overlap. Reconcile exact commit/file overlap and choose a single integration order. PR #8 contains a pytest-install fix, but the separate #7 PR remains open.

## Feed safety hardening just committed to PR #8

- Freshness now tracks **accepted order-book sequence progress**, not merely received WebSocket messages.
- Diagnostics add `last_book_update_age_seconds` while preserving `last_event_age_seconds` for message-receipt monitoring.
- The read-only order-book endpoint refuses disconnected, unsynchronized, never-progressed, or stale books.
- Regression tests cover stale-book rejection, duplicate events not refreshing freshness, and valid sequence progress restoring book availability.

The latest PR #8 head has CI running. This code has not yet been certified by those checks or by live exchange observation.

## CI and deployment snapshot

- PR #8, earlier head: backend, combined-paper, Layer 1 sync, frontend build, and infrastructure checks were green. The new commits are pending CI.
- PR #9: all five recorded checks passed on its current head.
- PR #10: both recorded checks passed on its current head (424 backend tests + 15 subtests were reported in its validation history).
- Vercel preview/production checks for current PR heads are blocked by the Hobby deployment quota (over 100 deployments/day). Older commits have READY deployments; these are **not** the current PR heads. No current feature-head deployment is certified.
- Do not trigger additional deployment attempts until quota recovers and deployment is explicitly approved.

## Android artifact verification (shell only)

- `android-remote-shell` head: `f55a42484a211b4bb54d25b27275b6b86f7cbbaa`
- GitHub Actions build-apk: completed successfully (25 Nov 2026).
- Artifact: `OrderFlow-Scalper-Remote-Shell-APK`, ID `15000014500`, ZIP size 3,455,290 bytes, expires 9 Dec 2026.
- Artifact ZIP was downloaded and verified to contain `app-debug.apk` (3,836,358 bytes). APK SHA-256: `3ed5da427fed87cf0f35d8b8a118777e542567e48e06e7bff3717fe49d518afb`.
- APK package manifest was not inspected (Android inspection tools unavailable in this runtime), and it has **not** been installed or tested on a physical phone.
- Shell config points to `https://orderflow-scalper-ivory.vercel.app`; the app code on this branch remains illustrative placeholder data. Do not use this APK for the planned paper demo.

## Release checklist

- [x] Core code and deterministic test coverage exist for scanner, nine-layer engine, trade management, risk, absorption/liquidity, and paper lifecycle.
- [x] Current PR #9 risk-engine CI green.
- [x] Current PR #10 absorption/liquidity CI green.
- [x] Android shell APK build exists and its artifact ZIP was verified.
- [ ] PR #8 freshness hardening CI green.
- [ ] Consolidate feature and validation branches into one reviewed integration branch without losing fixes.
- [ ] Live public feed certification: freshness, synchronization, sequence continuity, reconnect/resnapshot, and sustained uptime checkpoints.
- [ ] Validate scanner, nine-layer traces, lifecycle, fixed/trailing SL and trailing TP, risk blockers, persistence/restart recovery, and mobile telemetry with real feed data.
- [ ] Verify backend/frontend integration and API configuration, then deploy the reviewed integration build (requires approval and available deployment quota).
- [ ] Build APK from integrated monitoring app; verify artifact/package/signature and release notes.
- [ ] Physical Android install test: app launch, login/session, network switching, background/foreground, reconnect, live dashboard, scanner/decision traces, paper positions, risk monitor, emergency halt.
- [ ] Controlled paper validation: 100 closed trades over at least 14 days, with after-fee metrics and no unmanaged positions or unintended duplicate entries. This is a validation target, not a profitability guarantee.

## Next action

Finish and review the PR #8 freshness change/CI, then perform branch consolidation. The placeholder Android shell cannot be promoted to the release APK until it is replaced or connected to the real monitoring frontend.
