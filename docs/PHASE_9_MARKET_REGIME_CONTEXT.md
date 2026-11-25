# Phase 9 — Volatility, Market Regime & Broader Context

## Scope
A context classification engine with a **dummy OHLCV API provider** for integration. Mock candles are deterministic, marked `DUMMY`, and never treated as live data. Adapter can later be replaced by real exchange OHLCV endpoints.

## Endpoints
- `GET /api/market-context/status`
- `GET /api/market-context/candles/{symbol}?interval=1m&limit=120` (dummy data)
- `GET /api/market-context/regime/{symbol}?interval=1m&limit=120&fast_period=12&slow_period=36`

## Classifications
Trend: UPTREND / DOWNTREND / RANGING
Volatility: EXPANSION / COMPRESSION / NORMAL
Composite: TRENDING_VOLATILE / TRENDING_LOW_VOL / RANGE_VOLATILE / RANGE_COMPRESSION / MIXED_OR_NORMAL
Also includes a volatility spike heuristic and average-close/range/return-volatility metrics.

## Dummy provider
Provider: dummy_ohlcv_api. Data explicitly includes `data_mode=DUMMY`, `is_live=false`, and a mock disclaimer. Not suitable for trading, strategy validation, or PnL claims.

## Limitations
Initial thresholds are heuristics and require future backtesting/calibration. No signals or orders are generated.

## Validation
Tests are authored but not run against the repository environment.
