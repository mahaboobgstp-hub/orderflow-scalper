# OrderFlow Scalper — Release Readiness Snapshot

**Audit date:** 28 November 2026  
**Target:** Android monitoring APK + observable, controlled paper/demo validation  
**Execution safety:** PAPER/DEMO only. Real exchange execution must remain disabled.

## Highest-priority release blocker

The current Android artifact is a monitoring candidate, not a release. The APK retrieved and inspected in Run 51 contains dashboard, feed monitor, test center, live activity, positions/trades, watchlist, and controls/settings screens with backend API wiring. However, its manifest and frontend inspection found **debuggable=true**, **allowBackup=true**, and the control token stored in `localStorage`. Release signing has not been verified and no physical-device test has been completed. Harden the token storage/manifest and produce a release-signed APK before distribution.

Live-feed certification remains a separate critical functional gate: a green deterministic synchronization suite is not proof of live sequence continuity, reconnect/resnapshot recovery, or sustained feed health.

## Current main and PR audit

Main is `4603a5ee256d6f038d94aaa6e9855441f56942f7`. The main branch protection API reports protection disabled (no required checks). Do not merge without explicit approval and independent review.

| PR | Head / base | Current status | CI / deployment evidence |
|---|---|---|---|
| [#15 — Layer 1/2 integration](https://github.com/mahaboobgstp-hub/orderflow-scalper/pull/15) | `validation/layers1-2-mainline-20261126-run11` → `main` | Open, 74 ahead / 0 behind, 16 files, mergeable | 6/6 Actions green at head `235dc37d`; 2/2 Vercel preview contexts success |
| [#11 — Phase A diagnostics](https://github.com/mahaboobgstp-hub/orderflow-scalper/pull/11) | `feature/observability-trader-transparency` → `main` | Open, 218 ahead / 2 behind, 17 files | 4/4 Actions green at `8c6625f1`; no commit status contexts returned at this head |
| [#9 — Phase E risk](https://github.com/mahaboobgstp-hub/orderflow-scalper/pull/9) | `feature/phase-e-risk-engine` → `main` | Open, 75 ahead / 65 behind; mergeability false | 5/5 Actions green; Vercel rate-limited |
| [#10 — Phase F absorption/liquidity](https://github.com/mahaboobgstp-hub/orderflow-scalper/pull/10) | `feature/phase-f-absorption-liquidity` → #9 | Open, 83 ahead / 65 behind main, stacked; mergeable | 2/2 Actions green at `e867082f`; Vercel rate-limited |
| [#1 — Layer 1 Binance snapshot bridge](https://github.com/mahaboobgstp-hub/orderflow-scalper/pull/1) | `fix/layer1-binance-snapshot-bridge` → `main` | Open, mergeability false | Previous backend run had 141 passed / 4 failed; current Vercel contexts rate-limited |
| [#7 — pytest infrastructure fix](https://github.com/mahaboobgstp-hub/orderflow-scalper/pull/7) | `fix/infra-pytest-dependency-20261126` → `main` | Open, draft, 1 commit; mergeable | Vercel contexts success; main infrastructure workflow already installs pytest |
| [#13/#14 — Layer 1/2 validation duplicates](https://github.com/mahaboobgstp-hub/orderflow-scalper/pulls) | Separate `main)-targeted validation branches | Open, draft, overlapping | CI history green; Vercel contexts are mixed/rate-limited |
| #2–#6 — older validation/fix branches | Multiple branches → `main` | Open and overlapping | Require reconciliation; do not cherry-pick blindly |

PR #8 transparency/feed/runtime bundle is **merged**, not open. Its latest accepted-book-progress freshness hardening is part of main. The previous checklist incorrectly listed #8 as open and described the main APK as an entirely placeholder dashboard; both statements are corrected here.

## Branch consolidation recommendation

1. Use PR #15 as the current Layer 1/2 integration candidate: it is current with main, has 6/6 Actions green, and its Vercel preview contexts succeeded.
2. Port only the unique diagnostics work from #11 after file-by-file comparison; do not merge its 218-commit history wholesale because it is diverged by two main commits.
3. Reconcile Phase E (#9) and Phase F (#10) separately. #9 is 65 behind and currently non-mergeable; #10 is stacked on #9 and also 65 behind. Do not attempt to merge this stack yet.
4. Review #1 and #13/#14 for duplicate Layer 1/2 changes; #1 is currently non-mergeable.
5. Preserve existing tests, avoid branch history rewrites, and require user approval before any merge.

## Feed safety and Phase A certification

Main contains the Phase A freshness contract: accepted sequence-progress timestamps are separate from raw message receipt; duplicate/old events must not refresh usable-book freshness; disconnected, unsynchronized, never-progressed, or stale books are unavailable; reconnect/gap recovery requires successful snapshot bridge application.

CI proves deterministic behavior only. Live certification still requires observed public exchange events, synchronized book, accepted sequence continuity, actual disconnect/gap recovery, and sustained uptime with checkpoints. No live feed certification is claimed.

## Android artifact security and verification (Run 51)

- Artifact source: GitHub Actions main build (26 November 2026), run `45835509081`; artifact ID `15124937133`.
- APK size: 5,266,450 bytes. Package `com.orderflowscalper.app`, version 1.0/code 1, target SDK 34, min SDK 22.
- APK ZIP integrity and binary manifest parsing passed. SHA-256: `a84e82a7cc4eb460b4d0419283e58f72232bcd0390287155117fd7aa7a682a47`.
- Observed blockers: `debuggable=true`; `allowBackup=true`; control token in `localStorage`. APK signing was not independently verified with `apksigner`; physical install and device testing remain pending.
- The monitoring dashboard/API integration is partial, not complete. Watchlist/settings persistence and scanner/strategy integration remain unfinished; live backend connection has not been certified on-device.
- Run 51 proposed a memory-only token patch and aggregate APK blocker verifier on a local evidence branch. These changes are **not yet applied to the upstream product branch**.

## CI and deployment status

- PR #15: current head Actions 6/6 green; preview contexts success. Preview is not production deployment.
- PR #11: 4/4 Actions green; Vercel status contexts not returned for its current head.
- PR #9: 5/5 Actions green; Vercel rate-limit failures.
- PR #10: 2/2 Actions green; Vercel rate-limit failures.
- Main and PR #1 currently show Vercel rate-limit failures (“retry in 24 hours”). No deployment was triggered.
- TradeBridge branch has its own focused workflow. Its first run `46170027385` failed at compile because of invalid `from __future__` statements in models and store; both are fixed in commits `577d9762` and `cae96497`. The tests were skipped on that failed run; a manual workflow dispatch is still required.

## Release checklist

- [x] Core deterministic tests exist for scanner, nine-layer engine, trade lifecycle, risk, absorption/liquidity, and paper persistence.
- [x] PR #8 freshness/observability hardening merged into main.
- [x] PR #15 current-head deterministic CI green (6/6) and preview checks successful.
- [x] PR #11 current-head deterministic CI green (4/4).
- [x] Phase E #9 and Phase F #10 focused CI green on their respective heads.
- [x] Main APK artifact retrieved, integrity checked, and manifest/frontend inspected.
- [ ] Consolidate Layer 1/2 and Phase A diagnostics into a reviewed integration branch without losing changes.
- [ ] Live public feed certification: snapshot synchronization, sequence continuity, stale invalidation, reconnect/resnapshot, sustained uptime and checkpoint evidence.
- [ ] Validate scanner, nine-layer trace, trade lifecycle (fixed SL, trailing SL, TP), risk gates, absorption/liquidity, persistence/restart recovery with live feed and deterministic fixtures.
- [ ] Apply APK security hardening (token not persisted, backup disabled, release debuggable false), verify release signature and artifact checksum.
- [ ] Complete backend/frontend integration, then deploy the reviewed build (requires explicit approval and available quota).
- [ ] Build the integrated monitoring APK and verify artifact, package, signing, release notes.
- [ ] Physical Android install test: launch/login, network changes, background/foreground, reconnect, dashboard, scanner/decision traces, paper positions, risk monitor, emergency halt.
- [ ] Controlled paper validation: 100 closed trades over at least 14 days, after-fee metrics, adequate regime coverage, no unmanaged positions or unintended duplicate entries. This is a validation target, not a profitability guarantee.

## Next action

Resolve the Android release security blockers and continue feed certification using PR #15 as the base. Port unique PR #11 diagnostics in a controlled review, then reconcile Phase E/F. No merge or deployment until explicitly approved.
