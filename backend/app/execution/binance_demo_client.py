import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx

from app.config import settings


class BinanceDemoError(RuntimeError):
    pass


class BinanceDemoClient:
    def __init__(self):
        self.base_url = settings.binance_base_url.rstrip("/")
        self.api_key = settings.binance_api_key
        self.api_secret = settings.binance_api_secret

    def _require_credentials(self):
        if not self.api_key or not self.api_secret:
            raise BinanceDemoError(
                "Binance Demo API credentials are not configured."
            )

    async def _signed_request(
        self,
        method: str,
        path: str,
        params: dict,
    ) -> dict:
        self._require_credentials()

        payload = {
            **params,
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
        }

        query = urlencode(payload)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        url = f"{self.base_url}{path}?{query}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key}

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
            )

        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:500]

            raise BinanceDemoError(
                f"Binance Demo API error ({response.status_code}): {detail}"
            )

        return response.json()
    async def _public_get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params or {})

        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:500]

            raise BinanceDemoError(
                f"Binance Demo public API error ({response.status_code}): {detail}"
            )

        return response.json()

    async def get_exchange_info(self) -> dict:
        return await self._public_get("/fapi/v1/exchangeInfo")

    async def get_symbol_price(self, symbol: str) -> dict:
        return await self._public_get(
            "/fapi/v1/ticker/price",
            {"symbol": symbol.upper()},
        )
    async def get_account(self) -> dict:
        return await self._signed_request(
            "GET",
            "/fapi/v2/account",
            {},
        )

    async def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
    ) -> dict:
        return await self._signed_request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": symbol.upper(),
                "side": side.upper(),
                "type": "MARKET",
                "quantity": quantity,
            },
        )
