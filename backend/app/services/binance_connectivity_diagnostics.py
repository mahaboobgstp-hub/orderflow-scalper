"""Read-only Binance connectivity diagnostics. Never places orders."""
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import httpx

from app.config import settings


async def _public_probe(base: str, path: str, params=None):
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(base + path, params=params or {})
        response.raise_for_status()
        return response.json()


async def _signed_account_probe(base: str, key: str, secret: str):
    payload = {"timestamp": int(time.time() * 1000), "recvWindow": 5000}
    query = urlencode(payload)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{base}/fapi/v2/account?{query}&signature={signature}"
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(url, headers={"X-MBX-APIKEY": key})
        response.raise_for_status()
        data = response.json()
    # Return minimal metadata, never balances, IDs, or credentials.
    return {
        "status": "connected",
        "can_trade_flag": data.get("canTrade"),
        "can_withdraw_flag": data.get("canWithdraw"),
        "can_deposit_flag": data.get("canDeposit"),
        "asset_count": len(data.get("assets", [])),
        "position_count": len(data.get("positions", [])),
    }


async def run_binance_diagnostics():
    demo_base = settings.binance_base_url.rstrip("/")
    live_base = "https://fapi.binance.com"
    result = {
        "test_scope": "read_only_connectivity",
        "order_placement_attempted": False,
        "live_trading_attempted": False,
        "demo": {},
        "live_public": {},
        "live_authenticated": {},
    }

    # Demo public REST tests via the backend.
    try:
        info = await _public_probe(demo_base, "/fapi/v1/exchangeInfo")
        ticker = await _public_probe(demo_base, "/fapi/v1/ticker/price", {"symbol": "BTCUSDT"})
        result["demo"]["public_rest"] = {
            "status": "connected",
            "btc_price_received": bool(ticker.get("price")),
            "btc_price": ticker.get("price"),
            "exchange_symbols_count": len(info.get("symbols", [])),
        }
    except Exception as exc:
        result["demo"]["public_rest"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}

    # Demo authenticated account read.
    if settings.binance_api_key and settings.binance_api_secret:
        try:
            result["demo"]["authenticated_read"] = await _signed_account_probe(demo_base, settings.binance_api_key, settings.binance_api_secret)
        except Exception as exc:
            result["demo"]["authenticated_read"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}
    else:
        result["demo"]["authenticated_read"] = {"status": "not_configured", "required_env": ["BINANCE_DEMO_API_KEY", "BINANCE_DEMO_API_SECRET"]}

    # Live public REST tests via the backend.
    try:
        info = await _public_probe(live_base, "/fapi/v1/exchangeInfo")
        ticker = await _public_probe(live_base, "/fapi/v1/ticker/price", {"symbol": "BTCUSDT"})
        result["live_public"] = {
            "status": "connected",
            "btc_price_received": bool(ticker.get("price")),
            "btc_price": ticker.get("price"),
            "exchange_symbols_count": len(info.get("symbols", [])),
        }
    except Exception as exc:
        result["live_public"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}

    # Live authenticated read-only account endpoint; does not place trades.
    live_key = os.getenv("BINANCE_LIVE_API_KEY", "")
    live_secret = os.getenv("BINANCE_LIVE_API_SECRET", "")
    if live_key and live_secret:
        try:
            result["live_authenticated"] = await _signed_account_probe(live_base, live_key, live_secret)
        except Exception as exc:
            result["live_authenticated"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}
    else:
        result["live_authenticated"] = {"status": "not_configured", "required_env": ["BINANCE_LIVE_API_KEY", "BINANCE_LIVE_API_SECRET"]}

    return result
