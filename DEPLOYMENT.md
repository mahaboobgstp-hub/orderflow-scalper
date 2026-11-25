# OrderFlow Scalper — deployment

## Docker
Build from the repository root:
`docker build -t orderflow-scalper-api .`
Run:
`docker run --rm -p 8000:8000 -e PORT=8000 orderflow-scalper-api`
Health: `GET /health`; readiness/diagnostics: `GET /api/monitoring/diagnostics`.

## Render
This repository includes a Render Docker service blueprint. Review settings and configure secrets only in the provider dashboard. Public exchange WebSockets and demo execution are disabled by default.

## Security
- Never commit API keys or .env files.
- Keep DEMO_EXECUTION_ENABLED=false until demo credentials and safeguards are verified.
- Use a secret manager/environment variables for credentials.
- Deployment does not enable real-money execution.

## Limitations
Current health checks report process/component initialization, not verified exchange connectivity. Paper-trading and market data remain in-memory. Restart recovery of paper positions is not durable yet; use a persistent store in a later validated stage.
