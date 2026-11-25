# Phase 11 — Paper Trading Engine

## Purpose
A strictly simulated trading engine that supports one net open position per symbol, manual paper market-entry, price marking, simulated close, account metrics and trade history.

## Endpoints
- `GET /api/paper/status`
- `GET /api/paper/account`
- `POST /api/paper/orders` (market-style simulated fill using supplied price)
- `POST /api/paper/mark-price` (mark open positions using supplied price)
- `POST /api/paper/close/{symbol}` (manual simulated close using supplied price)
- `GET /api/paper/history?limit=100`
- `POST /api/paper/reset` (reset session/equity and clear data)

## Simulation model
- Initial paper equity defaults to $10,000.
- Leverage is limited to 1x–5x.
- Simulated fees default to 0.04% per side.
- Entry requires sufficient simulated cash for initial margin plus fee.
- One open net position per symbol (no pyramiding/hedging yet).
- Linear USDT-style PnL approximation: (exit-entry) × quantity × direction.
- The mark-price API uses caller-supplied prices; it is not automatically connected to exchange prices yet.
- State is in-memory only and lost when the backend restarts.

## Safety
No real order is sent. Every order and trade is marked PAPER_ONLY/FILLED_SIMULATED. This is a simulation, not an exchange execution emulator; slippage, latency, liquidation, funding, contract tick/lot filters, and stop/target management are not modeled in this phase.

## Validation
Tests added; not executed against repository runtime.
