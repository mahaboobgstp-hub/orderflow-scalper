# TradeBridge Progress — Run 11

**Checkpoint:** 2026-11-28  
**Branch:** \`feature/tradebridge-chat-execution\`  
**Head at start:** \`d98aba058ade95af8f66c941500287585b7c1003\`

## Completed in this scoped increment
- Fail-closed configuration: Testnet required, live execution rejected, endpoint restricted to the existing Binance Futures Demo host, bounded TTL/position/notional/quantity/leverage settings.
- Strict signal schema: USDT-margined symbols only, timezone-aware timestamps, 300-second maximum signal life, exactly one nonempty result for each of nine layers.
- Trade preview schema: stop-loss required and directionally valid, take-profit directionally valid, bounded leverage/slippage, preview TTL at most 120 seconds, immutable preview object and deterministic trade hash.
- Thread-safe in-memory registry: duplicate signal and preview IDs rejected, one preview per signal, exact \`TAKE POSITION\` phrase plus trade hash required, one-time approval and submission claim, stale checks, cancellation before submission, safe allowlisted execution summary, safe error-code allowlist, and event log with defensive copies.
- Focused regression suite: 47 passed; compileall passed. Fresh local clone reproduced the same focused suite.

## Not yet complete / safety gates
- No FastAPI routes are mounted; no MCP server/tool definitions exist yet.
- No market-price freshness provider, portfolio/account risk validation, order notional filter against current mark price, or exchange filter validation in TradeBridge service yet.
- The in-memory store is single-process only. It does not provide crash-safe idempotency or durable audit records.
- No order submit, status, cancel, or user-data-stream reconciliation route added in this increment.
- No credentials used; no demo orders submitted; no live trading path created.

## Branch / CI evidence
- TradeBridge branch exists, but no PR is open.
- Workflow triggers inspected: backend CI pushes only to \`main\` and pull requests targeting \`main\`; infrastructure workflow similarly targets \`main\`. Feature-branch commits alone will not run Actions.
- A draft PR would likely trigger Vercel preview checks/deployment. We did not create one because that could cause a deployment side effect without approval.
- Branch start history contains repeated scaffold commit messages and a config syntax fix; one later config-fix commit had no file changes. History is left intact rather than rewritten.

## ChatGPT MCP connection prerequisites
- OpenAI's current Help Center states custom MCP connections with full write actions are available for Business and Enterprise/Edu workspaces. Pro supports read/fetch-only MCP; Go is not listed as eligible for full write-action support.
- Connection needs a public HTTPS \`/mcp\` endpoint or Secure MCP Tunnel, an authentication mechanism, permission to create custom apps/plugins, risk-warning acknowledgment, tool discovery, and user review/confirmation for write actions.
- No connection or credential setup has been attempted. No withdrawals or transfers tools will be exposed.

## Next TradeBridge work
1. Add a service layer for server-side market-price freshness and risk validation.
2. Add preview/authorize/submit endpoints under control-token auth; keep execution unavailable by default and enforce Demo host at runtime.
3. Add clientOrderId/idempotency support and status/cancel, with safe reconciliation for ambiguous network outcomes.
4. Add durable audit and idempotency storage; require persistence before multi-instance use.
5. Implement narrow MCP tools (preview, approve/submit, status/cancel only) and validate with MCP Inspector.
6. Run CI through a PR only after explicit approval to avoid preview-deployment side effects.


## Run 12 — server-side risk validation (2026-11-28)

**Branch head after this increment:** `a875d18422c3de4503bf88fb28ab16da790d6e4b`

### Implemented
- Added side-effect-free `backend/app/tradebridge/risk.py` for preview validation against server-supplied market quote, exchange filters, and account-risk snapshots. This module never calls an exchange, reads credentials, or submits orders.
- Fail-closed freshness checks: quote <= 2 seconds, account-risk snapshot <= 5 seconds, exchange symbol rules <= 1 hour; timestamps must be timezone-aware and future clock skew <= 1 second.
- Hard-coded service risk bounds: spread <= 20 bps; per-trade stop risk <= 1% equity; aggregate stop risk <= 2% equity. Limits are not request fields.
- Enforces matching symbol, positive/non-crossed quote, quantity bounds and step alignment, stop/TP tick alignment, exchange minimum notional, configured notional/quantity/leverage caps, slippage versus mark, directional stop/TP geometry, position cap, available margin, and account snapshot sanity.
- Added `backend/tests/test_tradebridge_risk.py` with 26 focused regression tests for passing preview, stale/future data, symbol/quote integrity, spread, step/tick filters, notional, slippage, stop geometry, leverage, positions, margin, per-trade and aggregate risk.

### Local validation
- Focused test run: **26 passed**.
- Python compile check for the risk service and test file: passed.
- This run did not execute the full backend suite or GitHub Actions. Feature branch has no PR; no branch-triggered Actions run was observed.

### Still gated / not yet integrated
- Risk service is not yet mounted into FastAPI preview/authorization/submit routes; it must be wired to server-trusted quote, exchange filters, and account data, not client-supplied snapshots.
- No execution, credentials, or live trading path added. No demo order submitted.
- Persistent idempotency/audit and MCP tools remain unimplemented.


## Run 12 follow-up — freshness snapshots and immutable risk policy

- Tightened the risk validator so freshness and risk thresholds are module constants, not function arguments: quote age <= 2s, account snapshot age <= 5s, symbol-filter cache <= 1h, future timestamp skew <= 1s, spread <= 20 bps, per-trade stop risk <= 1% equity, total stop risk <= 2% equity.
- Added required timestamps to account-risk and exchange-rule snapshots; previews fail closed when either is missing/stale. Rejects existing portfolio risk already above cap and available margin greater than account equity.
- Price tick alignment now applies to protective stop/take-profit order prices, not the mark/bid/ask/reference fields used for market-order preview.
- Updated focused suite includes **26 cases**; local run after this hardening: **26 passed**. Python compilation passed. Full backend suite and GitHub Actions remain unrun.
- Commits: `027721e3` (hardcoded safety thresholds and snapshot freshness), `ce8635f7` (expanded regression tests). Branch head at this follow-up: `ce8635f7e0c384b15fc20f94f04564832beaeea0`.
- Risk validator remains isolated and not mounted into FastAPI; trusted quote/account/filter providers and auth routes must be wired before any preview is actionable. No demo orders, credentials, live execution, or deployment were used.


## Run 12 final checkpoint — 2026-11-28

- Confirmed the feature branch head is `ca0ed19e7f5c8c720d8fb7c260a6f4f97f16081b`; latest risk code blob `c27f4583`, test blob `ac0c7735`. GitHub confirms the remote test file has 26 test functions and the remote validator contains fixed freshness/risk constants.
- Feature branch remains PR-less; commit-associated Actions run list is empty. Combined status still shows the two Vercel build-rate-limit failures (no deployment was triggered).
- PR #11 current head `8c6625f1`: 4/4 workflows completed successfully. PR #15 current head `235dc37d`: 6/6 workflows completed successfully; both Vercel status contexts are success on this PR head. Main remains `4603a5ee` and has no commit-associated workflow runs returned.
- Local focused validation: 26 tests passed; py_compile passed. The tests cover 26 validator cases; no full backend test run is claimed.


## Run 13 — read-only Demo snapshot provider (2026-11-28)

- Added `backend/app/tradebridge/snapshot_provider.py`, which obtains market mark price, best bid/ask, exchange symbol rules, account snapshot, and all open orders through the existing Binance Demo client. It does not submit orders.
- Added read-only public client methods for `/fapi/v1/premiumIndex` (mark), `/fapi/v1/ticker/bookTicker` (best bid/ask), and signed `/fapi/v1/openOrders` (all open orders). Open-orders responses are type-checked as a list.
- Provider fails closed if TradeBridge is disabled, configuration/endpoint validation fails, market data requests exceed 2 seconds, account snapshot requests exceed 5 seconds, symbol metadata is not an active USDT perpetual or filters are missing/malformed, any open order exists, or any nonzero position exists (existing protective-stop risk is not reconciled).
- Snapshot timestamps are receipt timestamps; market/account network duration is bounded before risk validation. This is not exchange-source timestamp proof and must be improved/reconciled before order submission.
- Added `backend/tests/test_tradebridge_snapshot_provider.py`: **17 tests** covering parsing, symbol/quote mismatches, malformed/nonpositive data, exchange filters, positions/open orders, account margin sanity, provider disabled, and endpoint mismatch.
- Local isolated harness: **17 passed** and compileall passed. The isolated harness used stubs for existing config/client/risk dependencies; this is not the full repository test run.
- Commit sequence: `c8afe52b` (provider), `c35ac4a1` (tests), `cf5f2d84` (Demo client public/account-read methods). Branch remains `feature/tradebridge-chat-execution`; no PR and no Actions run. No credentials, orders, live execution, or deployment used.

### Remaining
- Provider is not yet wired to FastAPI preview routes. The next safe step is an authenticated, read-only preview endpoint that invokes this provider and risk validator and stores only a preview; approval and order submission must remain unavailable until persistent idempotency and explicit Testnet execution gates are implemented.
- TradeBridge remains disabled by default. No open order or position data is interpreted as zero risk unless the complete snapshots are present and verified.


### Run 13 CI follow-up

- Added `.github/workflows/tradebridge-focused.yml`, a branch-scoped, read-only GitHub Actions workflow. It triggers only on the TradeBridge feature branch for relevant paths (and on PRs to main), installs backend requirements + pytest, compiles the TradeBridge modules and Demo client, then runs the three focused TradeBridge suites. Workflow permissions are `contents: read`; it does not use secrets, deploy, or submit orders.
- The new workflow commit is `0bda9218`. Its run status is checked separately; local tests do not substitute for CI.
