# Phase 13 — Backtesting & Performance Analytics

## Scope
Offline candle-array backtests with EMA crossover baseline, risk-based position sizing, notional cap, fixed stop, fixed target, optional trailing stop, fees and percentage slippage. It produces closed trade ledger, equity curve, win/loss counts, win rate, profit factor, average win/loss, max drawdown, return, long/short attribution.

## API
- GET /api/backtest/status
- POST /api/backtest/run with candles and config

Input candles: ordered OHLC rows with optional timestamp. The API never fetches market data; user-supplied historical data is required. Config defaults: $10,000, risk 0.5%, notional cap 25%, 3x, EMA 12/36, SL 1%, TP 2%, trailing stop disabled, fees 0.04% per side, slippage 0.02% per fill.

## Limitations
This is an EMA-cross baseline, not the order-book scalping strategy. Candle intrabar order is unknowable; stop is prioritized when stop and target are both touched. No funding, liquidation, exchange lot filters, market impact, latency, or partial fills. Backtest is offline and not a guarantee of future performance. No tests or live API validation have been run in this phase.
