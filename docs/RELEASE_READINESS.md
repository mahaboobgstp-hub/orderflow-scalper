# OrderFlow Scalper — Release Readiness Snapshot

**Audit date:** 28 November 2026  
**Target:** Secure Android monitoring app + controlled paper/demo validation  
**Execution safety:** Paper/demo only. Live exchange execution remains disabled.

## Highest-priority remaining blocker

The memory-only control-token patch is present on `security/run40-memory-only-token`, but is **not integrated into main**. Main `frontend/src/App.jsx` still persists `ofs_token`. Do not enter a backend control token into the main-branch APK.

## Run 41 milestone

- Fixed the scanner test failure: the destructured-storage detector referenced an out-of-scope `names` variable.
- Corrected optional-call normalization for `?.(`.
- Added `scripts/**` to Android and web-check workflow path filters so scanner changes trigger CI.
- Local frontend tests: **19/19 passed**.
- GitHub Actions run **46107321060**: successful on code commit `bfed3db4792f0b9a3550f3369e5d8661b85cbcd7`. All steps passed: frontend unit tests, source token scan, frontend build, production-bundle token scan, Android sync, APK build, artifact upload.
- Artifact **15248261373**, `OrderFlow-Scalper-Android-APK`, downloaded and verified; expires **12 Dec 2026**.
- APK candidate size: **5,266,490 bytes**. ZIP integrity passed. Source and extracted APK JavaScript token-storage scans passed (0 findings).
- APK SHA-256: `d2b9853d847e7477aafb3321ba0df426b3b380c5c5a7ad71e568aff43efb6d7d`.
- APK bundle JS SHA-256: `b7e8cbf9243be59981bb50c29b1bb170610b4847df9819f71fdb1691854df2d6`.
- Artifact ZIP SHA-256: `dc56aee515f991ab9b6bca3f8db0ac54296894c5c6d3259e00c8f640a4784788`.
- `jarsigner -verify` reports `jar verified`, with JAR-stream warnings. Android `apksigner`, `aapt`, `adb`, and `bundletool` are unavailable; v2/v3 signature and manifest verification remain incomplete.
- APK is a **debug build**, not release-signed, and not device-tested.

## Main and PR audit

- Main: `4603a5ee256d6f038d94aaa6e9855441f56942f7`.
- Main Actions: 7 previously recorded successful workflow runs on 26 Nov; no newer main run returned.
- Open PRs: 13. Core heads: #11 `329f0e3f`, #15 `7a876b5e`, #9 `f10a9876`, #10 `e867082f`, #13 `df9521aa`, #14 `69482a83`, #7 `60f1f439`, #1 `b40a2620`.
- PR #11 feed observability and #15 L1/L2 consolidation overlap; #10 is stacked on #9. No merges were performed.
- Exact ahead/behind comparisons were not refreshed because GitHub compare requests were rejected by the connector.

## Deployment audit

- Primary production: READY at `ba0cdb9`, behind main.
- Secondary production: READY at `13e16ee`, behind main.
- Vercel status contexts on feature commits report rate-limit failures. Existing token-branch preview is READY at older commit `3f2558b4`, not the current branch head.
- No deployments initiated.
- Render workspace selection and fresh Supabase persistence/recovery telemetry were not verified this run.

## Checklist

- [x] Main monitoring UI identified (older placeholder-dashboard statement was stale).
- [x] Memory-only token patch exists on feature branch.
- [x] Local frontend tests: 19/19.
- [x] Source token-storage scanner passed.
- [x] Production bundle scanner passed.
- [x] Android workflow built and uploaded APK artifact.
- [x] APK ZIP integrity and direct bundle scan passed.
- [x] Android CI passes on the security branch.
- [ ] Integrate security patch into main after review/approval.
- [ ] Reproducible lockfile and `npm ci`.
- [ ] Release-signing and Android v2/v3 signature/manifest inspection.
- [ ] Physical Android install and app/network/background tests.
- [ ] Consolidate overlapping feed/L1-L2 branches.
- [ ] Feed freshness, snapshot bridge, sequence continuity, reconnect/resnapshot certification.
- [ ] Nine-layer trace, scanner, trade lifecycle, fixed/trailing SL/TP, Phase E risk, Phase F absorption/liquidity runtime validation.
- [ ] Persistence/restart recovery and mobile/backend integration validation.
- [ ] Controlled paper validation: 100 closed trades over 14 days with no unmanaged positions or duplicate entries.

## Safety

No merge, production deployment, secret change, paper-session activation, or live order execution occurred.