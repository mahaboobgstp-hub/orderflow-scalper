# Phase 5 — Order Book Imbalance Detector

**Status:** Implementation committed; runtime/API validation pending  
**Scope:** Read-only detector. No trading or order placement.

## Features

- Raw bid/ask quantities and normalized imbalance ratio.
- Top-of-book imbalance.
- Rank-distance weighted multi-level imbalance (near levels receive greater weight).
- Configurable depth request from 1–20 levels (default 10).
- Signed pressure score from -100 to +100.
- BUY_PRESSURE / SELL_PRESSURE / NEUTRAL classification (default absolute threshold 0.18).
- Per-side total quantity, largest level, and largest-level concentration (wall proxy).
- Rolling persistence samples, pressure change, change-per-second and acceleration-per-second².
- Data-quality score (depth coverage, persistence, and raw/weighted directional agreement). It is explicitly not a probability of a profitable trade.
- Strict refusal for unsynchronized, stale, over-age, integrity-error, empty, or crossed/locked books.

## API

- `GET /api/imbalance/status`
- `GET /api/imbalance/{exchange}/{symbol}?levels=10`

Supported exchange path values: `binance`, `bybit`, `delta`. A requested analysis returns HTTP 404 if no book is available, or HTTP 422 when the available book fails detector validation.

## Method

The raw imbalance is:

`(bid quantity - ask quantity) / (bid quantity + ask quantity)`

The weighted imbalance applies rank decay (`quantity / level rank`) to each side before calculating the same normalized ratio. The pressure threshold is configurable in the detector constructor. The persistence window defaults to 15 seconds and stores up to 20 samples per exchange/symbol in process memory.

## Safety/limitations

- Binance Phase 3 depth is still marked UNSYNCHRONIZED because its REST snapshot/delta bridge is not implemented. The Phase 5 detector will refuse to analyze it.
- Persistence and acceleration samples are created when this analysis endpoint is called; they are request-sampling metrics, not a dedicated high-frequency sampling loop.
- Large displayed orders may be canceled or spoofed. Wall concentration is a descriptive statistic, not proof of support/resistance.
- The quality score is not a win probability or predictive confidence.
- No entry, exit, leverage, or position decision is produced.

## Tests added

`backend/tests/test_phase5_imbalance_detector.py` covers BUY/SELL/NEUTRAL classifications, raw/weighted pressure, persistence metrics, level clamping, and rejection of unsynchronized, stale, old, and crossed books. Test execution in the complete backend environment is pending.
