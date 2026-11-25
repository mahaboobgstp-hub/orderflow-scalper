# OrderFlow Scalper — Backend Infrastructure Runbook

## Deployment
- Render service: `orderflow-scalper`
- Repository branch: `main`
- Dockerfile: repository root
- Public service URL: `https://orderflow-scalper.onrender.com`
- Region: Singapore
- Service plan: Render Free (may sleep after inactivity)

## Required/optional environment variables

| Variable | Required | Purpose |
|---|---|---|
| `SUPABASE_URL` | Yes for DB | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` or `SUPABASE_SECRET_KEY` | Yes for DB | Server-side database credential; never place in frontend |
| `SUPABASE_HEARTBEAT_INTERVAL_SECONDS` | No | Heartbeat interval (minimum 20 seconds; defaults to 60) |
| `DEMO_EXECUTION_ENABLED` | No | Defaults to `false`; enables only Binance Futures Demo execution |
| `BINANCE_DEMO_API_KEY` | No | Binance Futures Demo key |
| `BINANCE_DEMO_API_SECRET` | No | Binance Futures Demo secret |
| `BINANCE_DEMO_BASE_URL` | No | Defaults to Binance demo futures URL |
| `MAX_DEMO_ORDER_QUANTITY` | No | Defaults to `0.001` |
| `CONTROL_API_TOKEN` | For remote controls | Required before operator control endpoints accept commands |
| `FRONTEND_ORIGINS` | No | Comma-separated allowed origins; defaults to configured frontend origin |
| `LOG_LEVEL` | No | Defaults to `INFO` |

Never expose Supabase server credentials or control token in browser/frontend environment variables.

## Diagnostic endpoints
- `GET /`: API/service identity
- `GET /health`: basic liveness response
- `GET /ready`: initialized backend component readiness
- `GET /api/infrastructure/status`: aggregated infrastructure, database and market-data status
- `GET /api/database/status`: Supabase connectivity
- `GET /api/monitoring/diagnostics`: initialized component diagnostics
- `GET /api/monitoring/events`: recent in-memory events
- `GET /api/exchanges/status`: public exchange connections
- `GET /api/market-data/status`: primary order-book stream status
- `GET /api/market-data/unified/status`: unified feed status

## Database behavior
- The backend connects through Supabase REST/PostgREST.
- The backend uses a server-side credential only.
- A startup heartbeat and recurring heartbeat are written to `engine_heartbeat` when the connection succeeds.
- Engine lifecycle state is written to `engine_state`.
- Startup/shutdown and HTTP 5xx events are written to `system_logs`.
- DB connection failures are reported and do not crash the API process; this is intentional so the service can be diagnosed. DB-dependent features must remain unavailable until verified.

The repository module provides server-side write helpers for decisions, signals, orders, positions, risk events, closed trades, snapshots, metrics and system logs. Paper simulator lifecycle events now feed an async persistence queue: simulated order/position opens, mark-price/trailing updates, management changes, and closes are persisted to orders, positions, trade_history, risk_events, and system_logs. Queue counters are exposed at `GET /api/paper/persistence/status`. The queue is best-effort and bounded; events can be lost if the queue fills or DB writes fail. Paper account state itself is still in-memory and does not yet recover positions/account cash after a process restart.

## Safety
- Autonomous entry signal integration remains disabled until the nine-layer engine is validated.
- Live execution is not enabled or integrated.
- Binance demo execution defaults off.
- Paper engine is a simulator; currently its account/position state is in-memory and lost on process restart until paper-state persistence/recovery is implemented.
- Render Free is not suitable for uninterrupted 24/7 autonomous trading because it may sleep.

## Pre-test smoke sequence
1. Confirm Render deploy is `live` for the current main commit.
2. Open `/health` and `/ready`.
3. Open `/api/infrastructure/status`; confirm initialized components and inspect database connection.
4. Open `/api/exchanges/status` and `/api/market-data/status`.
5. Verify Supabase heartbeat rows and engine state rows in the dashboard.
6. Confirm paper execution is used for simulator testing and no live execution path is enabled.
7. Run the GitHub Actions backend checks and Docker build before calling a code update test-ready.

## CI checks
The `backend-infrastructure-checks.yml` workflow runs Python compilation, repository contract tests, and a Docker build on pushes and pull requests to `main`.
