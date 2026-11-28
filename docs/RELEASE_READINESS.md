# OrderFlow Scalper — Release Readiness

**Updated:** 28 Nov 2026, 05:52 IST  
**Main:** `4603a5ee256d6f038d94aaa6e9855441f56942f7`  
**Mode:** PAPER/DEMO only. Real exchange execution must stay disabled.

## Current highest-priority blocker

Mainline feed integrity: unbridged Binance depth updates mutate an unsynchronized book and refresh its book timestamp; trade events also refresh book freshness. The book is rejected by strategy gates, but diagnostics/freshness semantics are unsafe. Run 11 isolates a fix on a feature branch. The separate PR #15 contains a Binance snapshot-bridge integration but is unmerged and has no live recovery certification.

## Current release gates

- [x] Scanner, nine-layer decision engine, risk controls, paper engine, trade management, and persistence code exist.
- [x] Main recorded CI set: 7/7 green (26 Nov).
- [x] PR #11 latest Actions: 4/4 green.
- [x] PR #15 latest Actions: 6/6 green.
- [x] PR #9 Phase E: 5/5 green (branch 75 ahead / 65 behind main).
- [x] PR #10 Phase F: 2/2 green (stacked on #9).
- [x] PR #14 recovery: 4/4 green (2 ahead / 1 behind main).
- [x] PR #13 L1/L2 validation: 4/4 green (6 ahead / 1 behind main).
- [x] PR #7 infrastructure fix: 1/1 green (1 ahead / 65 behind main).
- [x] Run 11 freshness fix and regression tests committed on `fix/unified-book-message-freshness-run11`.
- [ ] Run 11 regression tests executed in CI (not run; see audit).
- [ ] Binance snapshot bridge integrated into mainline; verified with real feed and reconnect recovery.
- [ ] Consolidate stale/overlapping L1/L2, observability, Phase E/F, and recovery branches.
- [ ] Live feed certification: synchronization, sequence continuity, stale rejection, reconnect/resnapshot, sustained uptime.
- [ ] Nine-layer traces, scanner and paper entry/exit lifecycle verified with real feed data.
- [ ] Phase E risk gates and emergency halt verified in runtime.
- [ ] Phase F absorption/liquidity behavior and empirical calibration validated.
- [ ] Fixed SL, trailing SL, trailing TP, exit persistence and restart recovery demonstrated.
- [ ] Supabase runtime records and restart recovery verified (last audit: 12 tables, 0 rows).
- [ ] Mobile UI connected to real backend; placeholder shell replaced; token storage remains memory-only.
- [ ] Dependency lockfile/reproducible build; pin Capacitor asset tooling; APK credential-storage gate.
- [ ] Fresh APK artifact: manifest/package, signing, hash and install checks verified.
- [ ] Physical Android device tests: login, background/foreground, network/reconnect, feed monitor, scanner, decision trace, positions, stops, risk monitor, emergency halt.
- [ ] Controlled paper validation: 100 closed trades over ≥14 days; after-fee metrics, regime coverage, no unmanaged positions or duplicate entries.

## Deployment state

- Primary Vercel production READY at `ba0cdb9`, 80 commits behind main.
- Secondary production READY at `13e16ee`, 153 commits behind main.
- Latest observed PR #11 previews READY only on older `70542d1`; current head `e525094` is not deployment-verified.
- No deployments were triggered.
- Render inspection pending workspace confirmation.
- No APK release approval. Existing APK remains a shell/placeholder artifact and has not been installed on a physical device.

See [Run 11 audit](RELEASE_AUDIT_RUN11.md) for commit-level and branch details.
