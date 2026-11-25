"""Read-only Binance connectivity diagnostics. Never places orders."""
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import httpx
import websockets
import asyncio


async def _public_probe(base: str, path: str, params=None):
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(base + path, params=params or {})
        response.raise_for_status()
        return response.json()


async def _websocket_probe(url: str):
    try:
        async with websockets.connect(url, open_timeout=6, close_timeout=3, ping_interval=20, ping_timeout=20) as ws:
            message = await asyncio.wait_for(ws.recv(), timeout=6)
            return {"status": "connected", "first_message_received": bool(message)}
    except Exception as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


async def _binance_error(response: httpx.Response):
    """Extract safe Binance error details without including request URLs or credentials."""
    try:
        body = response.json()
        if isinstance(body, dict):
            return {"http_status": response.status_code, "binance_code": body.get("code"), "message": body.get("msg", "Unknown Binance error")}
        return {"http_status": response.status_code, "message": str(body)[:200]}
    except Exception:
        return {"http_status": response.status_code, "message": response.text[:200]}


async def _signed_account_probe(base: str, key: str, secret: str):
    async with httpx.AsyncClient(timeout=8) as client:
        # Use exchange server time to reduce timestamp drift-related authentication failures.
        server = await client.get(base + "/fapi/v1/time")
        server.raise_for_status()
        server_time = int(server.json()["serverTime"])
        local_time = int(time.time() * 1000)
        payload = {"timestamp": server_time, "recvWindow": 10000}
        query = urlencode(payload)
        signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        response = await client.get(
            f"{base}/fapi/v2/account?{query}&signature={signature}",
            headers={"X-MBX-APIKEY": key},
        )
        if response.is_error:
            raise RuntimeError(str(await _binance_error(response)))
        data = response.json()
    # Return minimal metadata, never balances, IDs, or credentials.
    return {
        "status": "connected",
        "server_time_sync_used": True,
        "local_server_clock_offset_ms": local_time - server_time,
        "can_trade_flag": data.get("canTrade"),
        "can_withdraw_flag": data.get("canWithdraw"),
        "can_deposit_flag": data.get("canDeposit"),
        "asset_count": len(data.get("assets", [])),
        "position_count": len(data.get("positions", [])),
    }


async def run_binance_diagnostics():
    demo_base = os.getenv("BINANCE_DEMO_BASE_URL", "https://demo-fapi.binance.com").rstrip("/")
    live_base = "https://fapi.binance.com"
    result = {
        "test_scope": "read_only_connectivity",
        "order_placement_attempted": False,
        "live_trading_attempted": False,
        "demo": {},
        "live_public": {},
        "live_authenticated": {},
    }

    try:
        info = await _public_probe(demo_base, "/fapi/v1/exchangeInfo")
        ticker = await _public_probe(demo_base, "/fapi/v1/ticker/price", {"symbol": "BTCUSDT"})
        result["demo"]["public_rest"] = {
            "status": "connected", "btc_price_received": bool(ticker.get("price")),
            "btc_price": ticker.get("price"), "exchange_symbols_count": len(info.get("symbols", [])),
        }
    except Exception as exc:
        result["demo"]["public_rest"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}

    result["demo"]["market_data_websocket"] = await _websocket_probe("wss://demo-fstream.binance.com/ws/btcusdt@depth@100ms")
    demo_key = os.getenv("BINANCE_DEMO_API_KEY", "")
    demo_secret = os.getenv("BINANCE_DEMO_API_SECRET", "")
    if demo_key and demo_secret:
        try:
            result["demo"]["authenticated_read"] = await _signed_account_probe(demo_base, demo_key, demo_secret)
        except Exception as exc:
            result["demo"]["authenticated_read"] = {"status": "failed", "error": str(exc)[:240]}
    else:
        result["demo"]["authenticated_read"] = {"status": "not_configured", "required_env": ["BINANCE_DEMO_API_KEY", "BINANCE_DEMO_API_SECRET"]}

    try:
        info = await _public_probe(live_base, "/fapi/v1/exchangeInfo")
        ticker = await _public_probe(live_base, "/fapi/v1/ticker/price", {"symbol": "BTCUSDT"})
        result["live_public"] = {
            "status": "connected", "btc_price_received": bool(ticker.get("price"),
            "btc_price": ticker.get("price"), "exchange_symbols_count": len(info.get("symbols", [])),
        }
    except Exception as exc:
        result["live_public"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}

    result["live_public"]["market_data_websocket"] = await _websocket_probe("wss://fstream.binance.com/ws/btcusdt@depth@100ms")
    live_key = os.getenv("BINANCE_LIVE_API_KEY", "")
    live_secret = os.getenv("BINANCE_LIVE_API_SECRET", "")
    if live_key and live_secret:
        try:
            result["live_authenticated"] = await _signed_account_probe(live_base, live_key, live_secret)
        except Exception as exc:
            result["live_authenticated"] = {"status": "failed", "error": str(exc)[:240]}
    else:
        result["live_authenticated"] = {"status": "not_configured", "required_env": ["BINANCE_LIVE_API_KEY", "BINANCE_LIVE_API_SECRET"]}
    return result
