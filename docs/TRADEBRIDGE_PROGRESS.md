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
