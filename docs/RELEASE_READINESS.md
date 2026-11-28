# OrderFlow Scalper — Release Readiness Snapshot

**Audit date:** 28 November 2026  
**Target:** Secure Android monitoring app + controlled paper/demo validation  
**Execution safety:** Paper/demo only. Live exchange execution remains disabled and must not be enabled.

## Highest-priority blocker

The memory-only control-token patch is present on `security/run40-memory-only-token`, but it is **not integrated into main**. Main `frontend/src/App.jsx` still loads `ofs_token` from localStorage. Do not use the main APK with the backend control token.

## Run 41 progress

- Fixed a scanner runtime error caused by `names` being out of scope in the destructured-storage detection regex.
- Fixed normalization of optional method calls (`?.(`), which previously could evade the scanner.
- Added `scripts/**` to the Android and web-check workflow path filters so scanner changes trigger CI.
- Local frontend suite: **19/19 passed**.
- Source scan: passed.
- APK candidate from earlier successful Run 40 build: ZIP integrity and JAR signature verified; bundled JS scan passed (0 findings).
- GitHub Android CI run `46107321060` was triggered on commit `bfed3db`; status was still in progress at audit time.

## Main and PR audit

- Main: `4603a5ee256d6f038d94aaa6e9855441f56942f7`.
- Main Actions: 7 recorded successful workflow runs on 26 Nov; no newer main run returned.
- Open PRs: 13. Core heads: #11 `329f0e3f`, #15 `7a876b5e`, #9 `f10a9876`, #10 `e867082f`, #13 `df9521aa`, #14 `69482a83`, #7 `60f1f439`, #1 `b40a2620`.
- PR #11 feed observability and #15 L1/L2 consolidation still overlap; #10 is stacked on #9. No merges were performed.
- Exact ahead/behind comparisons could not be refreshed because the GitHub compare endpoint was rejected by the connector.

## Deployment audit

- Existing primary production: READY at `ba0cdb9`, older than current main.
- Secondary production: READY at `13e16ee`, older than current main.
- Vercel status contexts on feature commits report rate-limit failures. Existing preview for the token branch is READY at older commit `3f2558b4`; not the current head.
- No deployments were initiated.
- Render workspace selection and fresh Supabase persistence/recovery telemetry were not verified this run.

## Android artifact evidence

- APK candidate built by successful GitHub Actions run `46104918912` from pre-scanner-fix token-security commit `c3d6f1ba`.
- Artifact ZIP integrity: passed.
- APK size: 5,266,491 bytes.
- APK SHA-256: `2a6c8fa1c09fb4d2a9f95a1a96ba7bcc4730f3b2c4bd4e96ebaf10cd6e406283`.
- Bundled JavaScript SHA-256: `b7e8cbf9243be59981bb50c29b1bb170610b4847df9819f71fdb1691854df2d6`.
- Token-storage scan of the actual APK bundle: **0 findings**.
- `jarsigner -verify`: `jar verified`. Android `apksigner`, `aapt`, `adb`, and `bundletool` are unavailable, so APK v2/v3 signature/manifest inspection and physical-device install are not verified.
- The APK is a debug build, not a final release-signed APK.

## Checklist

- [x] Main monitoring UI identified (the placeholder-dashboard statement in older docs was stale).
- [x] Memory-only token patch exists on feature branch.
- [x] Scanner tests run locally (19/19).
- [x] Source scanner passes.
- [x] APK candidate ZIP verified, signature checked, bundled token scan passes.
- [x] CI path filters now include scanner scripts.
- [ ] Current Run 41 GitHub Actions checks green.
- [ ] Reproducible dependency lockfile and `npm ci`.
- [ ] Integrate token patch into main only after review/approval.
- [ ] Consolidate overlapping feed and L1/L2 branches.
- [ ] Feed freshness, snapshot bridge, sequence continuity and reconnect/resnapshot sustained certification.
- [ ] Nine-layer trace, scanner, trade lifecycle, fixed/trailing SL/TP, Phase E risk gates and Phase F absorption/liquidity runtime validation.
- [ ] Persistence/restart recovery and mobile/backend integration validation.
- [ ] Release APK manifest and v2/v3 signature verification.
- [ ] Physical Android install and background/foreground/network-switch tests.
- [ ] Controlled paper validation: 100 closed trades over at least 14 days, with no unmanaged positions or unintended duplicate entries.

## Safety

No merge, production deployment, secret change, paper-session activation, or live order execution was performed.