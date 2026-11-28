"""Phase A consolidated diagnostics API contract for per-symbol feed records."""
import asyncio

from app import main


def test_observability_api_preserves_per_symbol_message_freshness_schema(monkeypatch):
    class FakeUnified:
        def get_status(self):
            return {
                "stale_after_seconds": 3.0,
                "feeds": {
                    "binance:BTCUSDT": {
                        "exchange": "binance",
                        "symbol": "BTCUSDT",
                        "messages_received": 17,
                        "last_message_age_seconds": 0.25,
                    },
                    "bybit:ETHUSDT": {
                        "exchange": "bybit",
                        "symbol": "ETHUSDT",
                        "messages_received": 8,
                        "last_message_age_seconds": 0.1,
                    },
                },
                "books": {
                    "binance:BTCUSDT": {
                        "synchronized": False,
                        "stale": True,
                        "integrity_error": "waiting for snapshot",
                        "age_seconds": None,
                        "best_bid": None,
                        "best_ask": None,
                    },
                    "bybit:ETHUSDT": {
                        "synchronized": True,
                        "stale": False,
                        "integrity_error": None,
                        "age_seconds": 0.2,
                        "best_bid": 2000.0,
                        "best_ask": 2001.0,
                    },
                },
                "exchanges": {},
                "trade_streams": {},
                "errors": {},
            }

    class FakePrimary:
        async def get_status(self):
            return {
                "connected": False, "synchronized": False, "stale": True, "healthy": False,
                "error_count": 4, "last_error": "demo depth reconnect failure",
            }

    class FakeExchanges:
        async def status(self):
            return {
                "exchanges": [
                    {
                        "exchange": "binance",
                        "symbol": "BTCUSDT",
                        "enabled": True,
                        "connected": True,
                        "last_message_age_seconds": 0.25,
                        "last_error": None,
                    },
                    {
                        "exchange": "bybit",
                        "symbol": "ETHUSDT",
                        "enabled": True,
                        "connected": True,
                        "last_message_age_seconds": 0.1,
                        "last_error": None,
                    },
                ]
            }

    state = main.app.state
    names = ("market_stream", "unified_market_data", "exchange_manager")
    originals = {name: getattr(state, name, None) for name in names}
    missing = {name: not hasattr(state, name) for name in names}
    state.market_stream = FakePrimary()
    state.unified_market_data = FakeUnified()
    state.exchange_manager = FakeExchanges()
    try:
        payload = asyncio.run(main.market_data_observability())
    finally:
        for name in names:
            if missing[name]:
                delattr(state, name)
            else:
                setattr(state, name, originals[name])

    primary = payload["primary_binance_demo_stream"]
    assert primary["error_count"] == 4
    assert primary["last_error"] == "demo depth reconnect failure"

    feeds = payload["unified_market_data"]["feeds"]
    assert feeds["binance:BTCUSDT"] == {
        "exchange": "binance",
        "symbol": "BTCUSDT",
        "messages_received": 17,
        "last_message_age_seconds": 0.25,
    }
    assert feeds["bybit:ETHUSDT"] == {
        "exchange": "bybit",
        "symbol": "ETHUSDT",
        "messages_received": 8,
        "last_message_age_seconds": 0.1,
    }
    # Message freshness is not the same as synchronized, healthy book state.
    assert payload["summary"]["fresh_message_feed_count"] == 2
    assert payload["summary"]["healthy_feed_count"] == 1
    assert payload["summary"]["synchronized_book_count"] == 1
    assert payload["summary"]["unified_book_count"] == 2
    assert payload["mode"] == "PUBLIC_MARKET_DATA_PAPER_ONLY"
    assert payload["live_execution_enabled"] is False
