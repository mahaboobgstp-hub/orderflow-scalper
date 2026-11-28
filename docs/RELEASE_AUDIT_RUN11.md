# OrderFlow Scalper — Run 11 Release Audit

**Audit time:** 28 Nov 2026, 05:52 IST  
**Main:** `4603a5ee256d6f038d94aaa6e9855441f56942f7`  
**Execution mode:** Public market data + paper/demo only. Real exchange execution must remain disabled.

## Release blocker selected

The mainline unified market-data engine still allows unbridged Binance depth messages to mutate its book and refresh the book timestamp, and trade messages refresh book freshness. Unsynchronized books are rejected by strategy gates, but the diagnostics/book state can misrepresent the freshness of depth data. This is a feed-integrity issue; Layer 3 and autonomous paper entry must remain gated until the snapshot bridge is integrated and live recovery is observed.

## Run 11 change

Feature branch: `fix/unified-book-message-freshness-run11`

- Commit `f46d9a11a1c5b4e45f9dadefab732aa4d1215e2f`: separate exchange message activity from book freshness; unbridged Binance depth is not applied to the unified book, remains unsynchronized/stale, records an integrity error, and cannot refresh the book clock.
- Commit `397939c2bc91a37d1bf69719fcfb2c9c4c58939c`: add regressions for unbridged Binance depth and trade messages not refreshing book age.
- Source/test blob SHAs were verified after commit.
- **Tests not executed:** GitHub branch Actions shows no run for this feature branch. Shell checkout failed because DNS resolution for github.com was unavailable. No PR was opened because a PR would automatically trigger Vercel preview deployment, which is not authorized in this task.

## GitHub snapshot

- Main: 7 recorded successful workflows on 26 Nov (backend, infra, frontend, Layer 3, Layer 9, combined paper, Android build).
- PR #11 — `feature/observability-trader-transparency`: head `e52509439ac177ece3b25ffd6caa5efea1c00b00`, **158 ahead / 2 behind main**. Latest Actions set: 4/4 green. PR base is stale.
- PR #15 — `validation/layers1-2-mainline-20261126-run11`: head `722a6d20197f360d36e3a095da2eaf1d5b1dff57`, **66 ahead / 0 behind main**. Latest Actions set: 6/6 green. This branch contains the Binance snapshot-bridge integration; it remains unmerged and lacks operational feed proof.
- PR #9 Phase E: **75 ahead / 65 behind main**, 5/5 recorded checks green.
- PR #10 Phase F: 8 commits ahead of PR #9, 2/2 recorded checks green; stacked on #9.
- PR #14 recovery: **2 ahead / 1 behind main**, 4/4 recorded checks green.
- PR #13 L1/L2 validation: **6 ahead / 1 behind main**, 4/4 recorded checks green.
- PR #7 pytest infrastructure fix: **1 ahead / 65 behind main**, 1/1 recorded check green.
- 13 open PRs total. No PR was merged.

## Vercel / deployment snapshot

- Primary production: READY, commit `ba0cdb9cc957b06e9bcc25dc0c935d574d7025a8`, **80 commits behind main**.
- Secondary production: READY, commit `13e16ee9e6ff89fa3e6e133fbf8a862b8bccf1f7`, **153 commits behind main**.
- Latest observed PR #11 previews are READY on older commit `70542d1afc85b503d03bcc27deca2b57ceffd3b0`; current PR head `e525094` has no verified matching preview.
- No deployment was triggered.

## Infrastructure and APK

- Render inspection remains blocked pending explicit workspace confirmation.
- Supabase last recorded audit: 12 core tables, 0 runtime rows; RLS enabled. Persistence/restart recovery not certified.
- Main Android workflow last recorded success: run `45835509081` on main commit `4603a5ee`. Workflow still uses `npm install` and unpinned `@capacitor/assets`; no verified lockfile or credential-storage gate is present in the main workflow.
- Existing APK is a remote-shell/placeholder UI, not the integrated monitoring app. No physical Android install/device test has been recorded.

## Checklist

- [x] Run 11 safety change committed to feature branch.
- [x] Regression tests authored.
- [ ] Run 11 CI: blocked (no workflow-dispatch tool; PR would trigger preview deployment; local clone blocked by DNS).
- [ ] Integrate/validate Binance snapshot bridge on mainline.
- [ ] Verify live depth freshness, sequence gaps, reconnect and snapshot recovery.
- [ ] Consolidate overlapping L1/L2 and observability branches after source reconciliation.
- [ ] Verify scanner, nine-layer trace, Phase E risk gates, Phase F detector and fixed/trailing SL/TP lifecycle.
- [ ] Demonstrate persistence and restart recovery with runtime records.
- [ ] Integrate mobile monitoring frontend/backend and remove placeholder data.
- [ ] Lock dependencies and add APK token-storage security gate.
- [ ] Build and inspect a fresh APK; verify manifest/signature/artifact.
- [ ] Install and test on physical Android device.
- [ ] Controlled paper validation: 100 closed trades over 14 days, after-fee metrics, regime coverage, no unmanaged positions/duplicate entries.

## Safety

No merge, production deployment, secret change, paper-session activation, or real exchange execution. CI green is not live-market certification or profitability proof.
