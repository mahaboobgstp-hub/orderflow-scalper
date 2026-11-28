# Run 41 — Release Audit and Scanner CI Fix

**Date:** 28 November 2026

## Defect confirmed from GitHub Actions

Run `46104924967` on the Run 40 security branch failed in `frontend/tests/tokenSession.test.mjs`. The destructured-storage scanner regex referenced `names` outside the block where it was declared, causing `ReferenceError: names is not defined` in 15 of 19 tests. The optional method-call normalization also left `?.(` unnormalized.

## Fix

- The destructuring detector now uses the storage alias in the current loop scope.
- Optional-call normalization runs before general optional-chain normalization.
- The Android workflow now watches `scripts/**`.
- The web-build-check workflow now watches `scripts/**` for push and pull_request events.

## Local verification

- `cd frontend && npm test`: **19 passed, 0 failed**.
- `node scripts/check-control-token-storage.mjs frontend/src`: PASS, 0 findings.
- Actual APK bundle extracted and scanned: PASS, 0 findings.
- APK artifact ZIP: `unzip -t` PASS.
- `jarsigner -verify`: PASS (`jar verified`).
- APK SHA-256: `2a6c8fa1c09fb4d2a9f95a1a96ba7bcc4730f3b2c4bd4e96ebaf10cd6e406283`.
- Bundle SHA-256: `b7e8cbf9243be59981bb50c29b1bb170610b4847df9819f71fdb1691854df2d6`.

## CI

Android workflow run `46107321060` was triggered by commit `bfed3db` and was in progress when checked. The latest commit that also updates the web workflow path filter is `45c6905f`; that web workflow only runs on main pushes or PRs targeting main, so it did not execute on this feature branch.

## Blockers

- Main still persists the backend control token.
- Android dependency lockfile is absent; workflow uses `npm install`.
- CI after scanner fix pending.
- Android SDK signature/manifest tooling and physical device testing unavailable.
- Vercel status checks are rate-limited; no deployment attempted.
- Feed, nine-layer, risk, absorption, trade lifecycle, persistence/recovery, and paper validation remain uncertified.
