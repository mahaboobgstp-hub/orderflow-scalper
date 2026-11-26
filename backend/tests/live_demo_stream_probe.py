"""Read-only, bounded live Binance Futures DEMO stream probe.

This script never uses credentials or sends trading requests. It only connects to
public demo market-data endpoints and validates snapshot-to-stream synchronization,
freshness, update-ID progression, and a bounded live imbalance-detector sample.
"""
from __future__ import annotations

import asyncio
import json
import time

from app.market_data.backend_stream import (
    BinanceOrderBookStream,
    REST_BASE_URL,
    WEBSOCKET_BASE_URL,
)
from app.services.imbalance_detector import OrderBookImbalanceDetector

DURATION_SECONDS = 60.0
POLL_SECONDS = 0.5
MIN_SYNC_SAMPLES = 60
MIN_UPDATE_ADVANCES = 20


def _require_demo_urls() -> None:
    if REST_BASE_URL != "https://demo-fapi.binance.com":
        raise RuntimeError(f"Refusing non-demo REST endpoint: {REST_BASE_URL}")
    if WEBSOCKET_BASE_URL != "wss://demo-fstream.binance.com":
        raise RuntimeError(f"Refusing non-demo WebSocket endpoint: {WEBSOCKET_BASE_URL}")


async def _safety_probe() -> dict[str, bool]:
    stream = BinanceOrderBookStream("BTCUSDT", max_book_age_seconds=3.0)
    stream.bids = {100.0: 1.0}
    stream.asks = {101.0: 1.0}
    stream.last_update_id = 10
    stream.connected = True
    stream.synchronized = False
    stream._last_event_received_at = time.monotonic()
    unsynchronized_rejected = await stream.get_order_book() is None

    stream.synchronized = True
    stream._last_event_received_at = time.monotonic() - 4.0
    stale_rejected = await stream.get_order_book() is None

    stream._last_event_received_at = time.monotonic()
    stream.bids = {101.0: 1.0}
    crossed_rejected = await stream.get_order_book() is None
    return {
        "unsynchronized_rejected": unsynchronized_rejected,
        "stale_rejected": stale_rejected,
        "crossed_rejected": crossed_rejected,
    }


async def run_probe() -> None:
    _require_demo_urls()
    stream = BinanceOrderBookStream("BTCUSDT", max_book_age_seconds=3.0)
    detector = OrderBookImbalanceDetector(history_size=20, persistence_window_seconds=15.0)
    started = time.monotonic()
    deadline = started + DURATION_SECONDS
    last_update_id = None
    sync_samples = 0
    detector_samples = 0
    update_advances = 0
    update_regressions = 0
    sync_losses = 0
    sync_recoveries = 0
    previous_sync = False
    previous_classification = None
    classification_switches = 0
    classifications: dict[str, int] = {}
    max_book_age = 0.0
    first_update_id = None
    last_sampled_id = None
    last_error_seen = None

    await stream.start()
    try:
        while time.monotonic() < deadline:
            status = await stream.get_status()
            is_sync = bool(status.get("synchronized")) and not bool(status.get("stale"))
            if previous_sync and not is_sync:
                sync_losses += 1
            if not previous_sync and is_sync and sync_samples > 0:
                sync_recoveries += 1
            previous_sync = is_sync

            error = status.get("last_error")
            if error and error != last_error_seen:
                last_error_seen = error

            if is_sync:
                book = await stream.get_order_book(depth=20)
                if book is not None:
                    sync_samples += 1
                    age = float(book.get("age_seconds", 0.0))
                    max_book_age = max(max_book_age, age)
                    update_id = int(book["last_update_id"])
                    if first_update_id is None:
                        first_update_id = update_id
                    if last_update_id is not None:
                        if update_id > last_update_id:
                            update_advances += 1
                        elif update_id < last_update_id:
                            update_regressions += 1
                    last_update_id = update_id
                    last_sampled_id = update_id

                    normalized = {
                        "exchange": "binance",
                        "symbol": "BTCUSDT",
                        "bids": book["bids"],
                        "asks": book["asks"],
                        "synchronized": True,
                        "stale": False,
                        "age_seconds": age,
                        "integrity_error": None,
                    }
                    result = detector.analyze(normalized, levels=10)
                    detector_samples += 1
                    classification = result["classification"]
                    classifications[classification] = classifications.get(classification, 0) + 1
                    if previous_classification is not None and classification != previous_classification:
                        classification_switches += 1
                    previous_classification = classification

            await asyncio.sleep(POLL_SECONDS)
    finally:
        await stream.stop()

    safety = await _safety_probe()
    duration = time.monotonic() - started
    evidence = {
        "mode": "read-only Binance Futures DEMO market data",
        "duration_seconds": round(duration, 2),
        "sync_samples": sync_samples,
        "detector_samples": detector_samples,
        "update_id_advances": update_advances,
        "update_id_regressions": update_regressions,
        "sync_losses": sync_losses,
        "sync_recoveries": sync_recoveries,
        "classification_counts": classifications,
        "classification_switches": classification_switches,
        "max_sampled_book_age_seconds": round(max_book_age, 3),
        "first_update_id": first_update_id,
        "last_update_id": last_sampled_id,
        "last_error_seen": last_error_seen,
        "safety_probe": safety,
    }
    print("LIVE_DEMO_EVIDENCE=" + json.dumps(evidence, sort_keys=True))

    failures = []
    if sync_samples < MIN_SYNC_SAMPLES:
        failures.append(f"insufficient synchronized samples ({sync_samples} < {MIN_SYNC_SAMPLES})")
    if detector_samples < MIN_SYNC_SAMPLES:
        failures.append(f"insufficient detector samples ({detector_samples} < {MIN_SYNC_SAMPLES})")
    if update_advances < MIN_UPDATE_ADVANCES:
        failures.append(f"insufficient update-ID advances ({update_advances} < {MIN_UPDATE_ADVANCES})")
    if update_regressions:
        failures.append(f"update-ID regressions observed ({update_regressions})")
    if max_book_age > 3.0:
        failures.append(f"sampled book age exceeded limit ({max_book_age:.3f}s)")
    if not all(safety.values()):
        failures.append(f"safety probe failed: {safety}")
    if failures:
        raise SystemExit("LIVE DEMO VALIDATION FAILED: " + "; ".join(failures))


if __name__ == "__main__":
    asyncio.run(run_probe())
