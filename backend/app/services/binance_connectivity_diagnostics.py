"""Read-only Binance connectivity diagnostics. Never places orders."""
import asyncio
import base64
import hashlib
import hmac
import os
import time
from urllib.parse import urlencode, quote

import httpx
import websockets


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


def _binance_error(response: httpx.Response):
    """Extract safe Binance error details without including request URLs or credentials."""
    try:
        body = response.json()
        if isinstance(body, dict):
            return {
                "http_status": response.status_code,
                "binance_code": body.get("code"),
                "message": body.get("msg", "Unknown Binance error"),
            }
        return {"http_status": response.status_code, "message": str(body)[:200]}
    except Exception:
        return {"http_status": response.status_code, "message": response.text[:200]}


def _sign_payload(payload: str, auth_type: str, secret: str = "", private_key_pem: str = ""):
    auth_type = auth_type.strip().lower()
    if auth_type == "hmac":
        if not secret:
            raise ValueError("HMAC secret is not configured.")
        return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if auth_type == "rsa":
        if not private_key_pem:
            raise ValueError("RSA private key is not configured.")
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            key_bytes = private_key_pem.replace("\\n", "\n").encode()
            private_key = serialization.load_pem_private_key(key_bytes, password=None)
            signature = private_key.sign(payload.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
            return base64.b64encode(signature).decode("ascii")
        except ImportError as exc:
            raise RuntimeError("RSA signing requires the cryptography package.") from exc
        except Exception as exc:
            raise RuntimeError(f"RSA signing failed: {type(exc).__name__}") from exc
    raise ValueError("Unsupported auth type. Configure HMAC or RSA.")


async def _signed_account_probe(base: str, key: str, auth_type: str, secret: str = "", private_key_pem: str = ""):
    async with httpx.AsyncClient(timeout=8) as client:
        # Estimate clock offset using the midpoint of the server-time request.
        t0 = int(time.time() * 1000)
        server = await client.get(base + "/fapi/v1/time")
        server.raise_for_status()
        server_time = int(server.json()["serverTime"])
        t1 = int(time.time() * 1000)
        midpoint = (t0 + t1) // 2
        offset_ms = server_time - midpoint
        timestamp = int(time.time() * 1000) + offset_ms
        local_server_clock_offset_ms = -offset_ms

        payload = {"timestamp": timestamp, "recvWindow": 10000}
        query = urlencode(payload)
        signature = _sign_payload(query, auth_type, secret, private_key_pem)
        response = await client.get(
            f"{base}/fapi/v2/account?{query}&signature={quote(signature, safe='')}",
            headers={"X-MBX-APIKEY": key},
        )
        if response.is_error:
            raise RuntimeError(str(_binance_error(response)))
        data = response.json()
    # Return minimal metadata, never balances, IDs, or credentials.
    return {
        "status": "connected",
        "auth_type": auth_type,
        "server_time_sync_used": True,
        "local_server_clock_offset_ms": local_server_clock_offset_ms,
        "can_trade_flag": data.get("canTrade"),
        "can_withdraw_flag": data.get("canWithdraw"),
        "can_deposit_flag": data.get("canDeposit"),
        "asset_count": len(data.get("assets", [])),
        "position_count": len(data.get("positions", [])),
    }


async def _auth_probe_for_env(base: str, key_env: str, secret_env: str, auth_type_env: str, private_key_env: str):
    key = os.getenv(key_env, "").strip()
    auth_type = os.getenv(auth_type_env, "hmac").strip().lower()
    secret = os.getenv(secret_env, "").strip()
    private_key = os.getenv(private_key_env, "")
    if not key:
        return {"status": "not_configured", "required_env": [key_env]}
    if auth_type == "rsa" and not private_key:
        return {"status": "not_configured", "auth_type": "rsa", "required_env": [private_key_env]}
    if auth_type == "hmac" and not secret:
        return {"status": "not_configured", "auth_type": "hmac", "required_env": [secret_env]}
    try:
        return await _signed_account_probe(base, key, auth_type, secret, private_key)
    except Exception as exc:
        return {"status": "failed", "auth_type": auth_type, "error": str(exc)[:240]}


async def run_binance_diagnostics():
    demo_base = os.getenv("BINANCE_DEMO_BASE_URL", "https://demo-fapi.binance.com").rstrip("/")
    live_base = os.getenv("BINANCE_LIVE_BASE_URL", "https://fapi.binance.com").rstrip("/")
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
    result["demo"]["authenticated_read"] = await _auth_probe_for_env(
        demo_base, "BINANCE_DEMO_API_KEY", "BINANCE_DEMO_API_SECRET",
        "BINANCE_DEMO_AUTH_TYPE", "BINANCE_DEMO_PRIVATE_KEY",
    )

    try:
        info = await _public_probe(live_base, "/fapi/v1/exchangeInfo")
        ticker = await _public_probe(live_base, "/fapi/v1/ticker/price", {"symbol": "BTCUSDT"})
        result["live_public"] = {
            "status": "connected", "btc_price_received": bool(ticker.get("price")),
            "btc_price": ticker.get("price"), "exchange_symbols_count": len(info.get("symbols", [])),
        }
    except Exception as exc:
        result["live_public"] = {"status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:240]}"}

    result["live_public"]["market_data_websocket"] = await _websocket_probe("wss://fstream.binance.com/ws/btcusdt@depth@100ms")
    result["live_authenticated"] = await _auth_probe_for_env(
        live_base, "BINANCE_LIVE_API_KEY", "BINANCE_LIVE_API_SECRET",
        "BINANCE_LIVE_AUTH_TYPE", "BINANCE_LIVE_PRIVATE_KEY",
    )
    return result
