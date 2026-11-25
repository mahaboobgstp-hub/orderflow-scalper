import os
import socket
from datetime import datetime, timezone
from typing import Any

import httpx


class SupabaseDatabase:
    """Minimal server-side Supabase REST client; credentials remain backend-only."""

    def __init__(self) -> None:
        self.url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "") or os.getenv("SUPABASE_SECRET_KEY", "")
        self.configured = bool(self.url and self.key)
        self.client: httpx.AsyncClient | None = None
        self.connected = False
        self.last_check: str | None = None
        self.last_error: str | None = None
        self.instance_id = os.getenv("RENDER_INSTANCE_ID") or socket.gethostname()

    async def start(self) -> None:
        if not self.configured:
            self.last_error = "Supabase credentials are not configured."
            return
        self.client = httpx.AsyncClient(
            base_url=f"{self.url}/rest/v1/",
            timeout=10.0,
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        await self.check_connection()
        if self.connected:
            await self.write_heartbeat("online", {"startup_check": True})

    async def check_connection(self) -> bool:
        self.last_check = datetime.now(timezone.utc).isoformat()
        if not self.configured or self.client is None:
            self.connected = False
            return False
        try:
            response = await self.client.get("engine_state", params={"select": "id", "limit": "1"})
            response.raise_for_status()
            self.connected = True
            self.last_error = None
        except Exception as exc:
            self.connected = False
            self.last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
        return self.connected

    async def write_heartbeat(self, status: str, details: dict[str, Any] | None = None) -> bool:
        if not self.connected or self.client is None:
            return False
        payload = {
            "instance_id": self.instance_id,
            "status": status,
            "mode": "DEMO_PAPER_ONLY",
            "details": details or {},
        }
        try:
            response = await self.client.post(
                "engine_heartbeat",
                json=payload,
                headers={"Prefer": "return=minimal"},
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            self.last_error = f"Heartbeat write failed: {type(exc).__name__}: {str(exc)[:240]}"
            return False

    async def status(self, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            await self.check_connection()
        return {
            "provider": "supabase",
            "configured": self.configured,
            "connected": self.connected,
            "last_check": self.last_check,
            "last_error": self.last_error,
            "credential_present": bool(self.key),
        }

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None


database = SupabaseDatabase()
