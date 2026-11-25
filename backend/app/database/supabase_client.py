import asyncio
import os
import socket
from datetime import datetime, timezone
from typing import Any

import httpx
import logging

logger = logging.getLogger(__name__)


class SupabaseDatabase:
    """Server-side Supabase REST client with safe diagnostics and retryable connectivity."""

    def __init__(self) -> None:
        self.url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")
        self.configured = bool(self.url and self.key)
        self.client: httpx.AsyncClient | None = None
        self.connected = False
        self.last_check: str | None = None
        self.last_error: str | None = None
        self.last_heartbeat: str | None = None
        self.instance_id = os.getenv("RENDER_INSTANCE_ID") or socket.gethostname()
        self.mode = "DEMO_PAPER_ONLY"
        self._heartbeat_task: asyncio.Task | None = None
        self._closed = False

    def _new_client(self) -> httpx.AsyncClient:
        headers = {
            "apikey": self.key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Supabase's new sb_secret keys are opaque API keys, not JWTs.
        # Send them only as apikey; Bearer is retained for legacy JWT keys.
        if not self.key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.key}"
        return httpx.AsyncClient(
            base_url=f"{self.url}/rest/v1/",
            timeout=httpx.Timeout(8.0, connect=5.0),
            headers=headers,
        )

    async def start(self) -> bool:
        self._closed = False
        if not self.configured:
            self.connected = False
            self.last_error = "Supabase credentials are not configured."
            logger.error("Supabase startup blocked: URL/key configuration missing")
            return False
        if self.client is None:
            self.client = self._new_client()
        if await self.check_connection():
            heartbeat_ok = await self.write_heartbeat("online", {"startup_check": True})
            if heartbeat_ok:
                logger.info("Supabase connection verified and startup heartbeat written")
            else:
                logger.error("Supabase connected but startup heartbeat write failed: %s", self.last_error)
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        else:
            logger.error("Supabase startup connection check failed: %s", self.last_error)
        return self.connected

    async def _heartbeat_loop(self) -> None:
        while not self._closed:
            try:
                interval = max(20, int(os.getenv("SUPABASE_HEARTBEAT_INTERVAL_SECONDS", "60")))
            except ValueError:
                interval = 60
            await asyncio.sleep(interval)
            if self._closed:
                return
            if not self.connected:
                await self.check_connection()
            if self.connected:
                await self.write_heartbeat("online", {"periodic": True})

    async def check_connection(self) -> bool:
        self.last_check = datetime.now(timezone.utc).isoformat()
        if not self.configured:
            self.connected = False
            self.last_error = "Supabase credentials are not configured."
            return False
        if self.client is None or self.client.is_closed:
            self.client = self._new_client()
        try:
            response = await self.client.get("engine_state", params={"select": "id", "limit": "1"})
            response.raise_for_status()
            self.connected = True
            self.last_error = None
            logger.info("Supabase REST connectivity check succeeded")
        except Exception as exc:
            self.connected = False
            self.last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            logger.error("Supabase REST connectivity check failed: %s", self.last_error)
        return self.connected

    async def _request(self, method: str, table: str, *, params: dict[str, Any] | None = None,
                       payload: dict[str, Any] | list[dict[str, Any]] | None = None,
                       prefer: str | None = None) -> Any:
        if not self.configured:
            raise RuntimeError("Supabase credentials are not configured.")
        if self.client is None or self.client.is_closed:
            self.client = self._new_client()
        headers = {"Prefer": prefer} if prefer else None
        response = await self.client.request(method, table, params=params, json=payload, headers=headers)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    async def insert(self, table: str, payload: dict[str, Any] | list[dict[str, Any]],
                     *, returning: bool = False) -> Any:
        result = await self._request("POST", table, payload=payload,
                                   prefer="return=representation" if returning else "return=minimal")
        self.connected = True
        self.last_error = None
        return result

    async def update(self, table: str, payload: dict[str, Any], *, filters: dict[str, str],
                      returning: bool = False) -> Any:
        result = await self._request("PATCH", table, params=filters, payload=payload,
                                   prefer="return=representation" if returning else "return=minimal")
        self.connected = True
        self.last_error = None
        return result

    async def upsert(self, table: str, payload: dict[str, Any] | list[dict[str, Any]],
                     *, on_conflict: str | None = None, returning: bool = False) -> Any:
        params = {"on_conflict": on_conflict} if on_conflict else None
        result = await self._request("POST", table, params=params, payload=payload,
                                   prefer="resolution=merge-duplicates,return=representation" if returning
                                   else "resolution=merge-duplicates,return=minimal")
        self.connected = True
        self.last_error = None
        return result

    async def select(self, table: str, *, columns: str = "*", filters: dict[str, str] | None = None,
                     limit: int = 100, order: str | None = None) -> Any:
        params: dict[str, Any] = {"select": columns, "limit": max(1, min(int(limit), 500))}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        return await self._request("GET", table, params=params)

    async def write_heartbeat(self, status: str, details: dict[str, Any] | None = None) -> bool:
        if not self.configured:
            return False
        payload = {
            "instance_id": self.instance_id,
            "status": status,
            "mode": self.mode,
            "details": details or {},
        }
        try:
            await self._request("POST", "engine_heartbeat", payload=payload, prefer="return=minimal")
            self.connected = True
            self.last_error = None
            self.last_heartbeat = datetime.now(timezone.utc).isoformat()
            logger.info("Supabase heartbeat write succeeded (%s)", status)
            return True
        except Exception as exc:
            self.connected = False
            self.last_error = f"Heartbeat write failed: {type(exc).__name__}: {str(exc)[:240]}"
            logger.error("Supabase heartbeat write failed: %s", self.last_error)
            return False

    async def status(self, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            await self.check_connection()
        return {
            "provider": "supabase",
            "configured": self.configured,
            "connected": self.connected,
            "last_check": self.last_check,
            "last_heartbeat": self.last_heartbeat,
            "last_error": self.last_error,
            "credential_present": bool(self.key),
            "instance_id": self.instance_id,
            "mode": self.mode,
        }

    async def close(self) -> None:
        self._closed = True
        task = self._heartbeat_task
        self._heartbeat_task = None
        if task and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self.client is not None:
            await self.client.aclose()
            self.client = None


database = SupabaseDatabase()
