# Phase 14 — Deployment, Monitoring & Recovery

## Deployment files
- Dockerfile (Python 3.12 slim, install requirements, copy backend, Uvicorn)
- render.yaml (Render Docker service blueprint; public WebSockets/demo execution disabled by default)
- .dockerignore (excludes secrets, git, caches, frontend artifacts)
- DEPLOYMENT.md (provider deployment steps/security notes)

## Monitoring
- GET /health: lightweight process health + uptime/environment/Python
- GET /api/monitoring/diagnostics: initialized component status
- GET /api/monitoring/events?limit=100: bounded in-memory event log
- HTTP middleware records status code, request duration, errors; logs 5xx and exceptions
- Startup/shutdown lifecycle wrapped with error logging and best-effort cleanup

## Recovery
- Container HEALTHCHECK uses /health.
- Render healthCheckPath is /health; platform can restart unhealthy services.
- WebSocket adapters already have reconnect infrastructure from Phase 2; actual exchange behavior still requires tests.
- Paper-trading state, market buffers, event logs and analytics state remain in-memory and are lost on process restart. Durable paper-position recovery is NOT implemented in this phase and should be added only after choosing/validating a persistent storage provider.
- No real-money execution enabled by this deployment configuration.

## Environment and secret handling
Configure secrets through provider environment settings. Do not commit credentials or .env files. Execution stays disabled by default. Public exchange connections disabled by default in the deployment blueprint.

## Validation status
Files were committed and fetched back from GitHub for presence verification. No Docker build, provider deployment, live health endpoint, exchange connection, backend syntax check, or unit test was executed. Phase 14 remains implemented but validation pending.
