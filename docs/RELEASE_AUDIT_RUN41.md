# Run 41 — Scanner Fix and Secure APK Candidate

**Date:** 28 November 2026

## Failure and fix

Run `46104924967` on the Run 40 security branch failed in `frontend/tests/tokenSession.test.mjs`. The destructured-storage detector referenced `names` outside its scope. Optional method calls `?.(` also weren't normalized correctly.

Fix:
- Destructuring detector now uses the storage alias in its loop scope.
- Optional-call normalization runs before general optional-chain normalization.
- Android workflow now watches `scripts/**`.
- Web build-check workflow now watches `scripts/**` for push and pull_request events.

## Local verification

- Frontend unit tests: **19/19 passed**.
- Source scan: PASS, 0 findings.
- APK bundle scan: PASS, 0 findings.
- Artifact ZIP integrity: PASS.
- `jarsigner -verify`: reports `jar verified`; warns that entries signed in JarFile are not signed in JarInputStream.
- Android SDK `apksigner`, `aapt`, `adb`, and `bundletool` are unavailable, so v2/v3 signature schemes, decoded manifest, and device install were not verified.

## CI milestone

- Workflow run: https://github.com/mahaboobgstp-hub/orderflow-scalper/actions/runs/46107321060
- Run ID: `46107321060`, commit `bfed3db4792f0b9a3550f3369e5d8661b85cbcd7`, conclusion **success**.
- All steps passed: frontend tests, source scan, frontend build, bundle scan, Android sync, debug APK build, artifact upload.
- Artifact: `OrderFlow-Scalper-Android-APK`, ID `15248261373`, expires 12 Dec 2026.
- APK size: 5,266,490 bytes.
- APK SHA-256: `d2b9853d847e7477aafb3321ba0df426b3b380c5c5a7ad71e568aff43efb6d7d`.
- Bundle JS SHA-256: `b7e8cbf9243be59981bb50c29b1bb170610b4847df9819f71fdb1691854df2d6`.
- Artifact ZIP SHA-256: `dc56aee515f991ab9b6bca3f8db0ac54296894c5c6d3259e00c8f640a4784788`.

## Remaining release gates

- Main still has persistent control-token storage; fix remains on the feature branch.
- Lockfile missing; build currently uses `npm install`, not `npm ci`.
- APK is debug-signed, not a release-signing build.
- No physical-device test.
- Feed, nine-layer, risk, absorption, trade lifecycle, persistence/recovery, and paper certification remain incomplete.
- Vercel rate-limit statuses remain; no deployment attempted.
