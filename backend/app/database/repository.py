"""Persistence repository for OrderFlow operational/trading records.

This module intentionally provides only backend-side methods. It is not exposed as a
public CRUD API and never accepts arbitrary table names from HTTP callers.
"""
from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

from app.database.supabase_client import database


class OrderFlowRepository:
    def __init__(self, db=database):
        self.db = db

    async def system_log(self, level: str, message: str, component: str | None = None,
                       details: dict[str, Any] | None = None) -> bool:
        try:
            await self.db.insert("system_logs", {
                "level": str(level).upper()[:16],
                "component": component,
                "message": str(message)[:2000],
                "details": details or {},
            })
            return True
        except Exception:
            return False

    async def engine_state(self, *, mode: str = "DEMO_PAPER_ONLY", status: str = "running",
                          execution_enabled: bool = False, config_version: int | None = None,
                          state: dict[str, Any] | None = None) -> bool:
        payload = {
            "mode": mode,
            "status": status,
            "execution_enabled": bool(execution_enabled),
            "active_config_version": config_version,
            "last_heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "state_json": state or {},
        }
        try:
            rows = await self.db.select("engine_state", columns="id,state_json", limit=1, order="updated_at.desc")
            if rows:
                # Preserve paper_account snapshots when lifecycle/heartbeat updates
                # write operational metadata without an explicit account payload.
                prior_state = rows[0].get("state_json") or {}
                incoming_state = state or {}
                if isinstance(prior_state, dict) and isinstance(incoming_state, dict):
                    merged_state = dict(prior_state)
                    merged_state.update(incoming_state)
                    payload["state_json"] = merged_state
                await self.db.update("engine_state", payload, filters={"id": f"eq.{rows[0]['id']}"})
            else:
                await self.db.insert("engine_state", payload)
            return True
        except Exception:
            return False

    async def load_paper_state(self) -> dict[str, Any]:
        """Load latest persisted paper account snapshot and open position rows."""
        state_rows = await self.db.select("engine_state", columns="state_json,updated_at", limit=1, order="updated_at.desc")
        open_positions = await self.db.select("positions", columns="id,symbol,side,quantity,entry_price,mark_price,stop_loss,take_profit,trailing_stop_price,trailing_take_profit_price,position_data,opened_at", filters={"status":"eq.OPEN"}, limit=500)
        return {"snapshot": (state_rows[0].get("state_json") if state_rows else {}) or {}, "open_positions": open_positions or []}

    async def save_paper_state(self, snapshot: dict[str, Any]) -> bool:
        return await self.engine_state(mode="DEMO_PAPER_ONLY", status="running", execution_enabled=False, state={"paper_account":snapshot})

    async def decision(self, symbol: str, decision: str, *, score: float | None = None,
                      layers: dict[str, Any] | list[Any] | None = None,
                      rationale: dict[str, Any] | list[Any] | None = None,
                      market_context: dict[str, Any] | None = None) -> Any:
        return await self.db.insert("decision_logs", {
            "symbol": symbol.upper(),
            "decision": decision,
            "final_score": score,
            "layer_results": layers or {},
            "rationale": rationale or {},
            "market_context": market_context or {},
        }, returning=True)

    async def signal(self, symbol: str, side: str, signal_type: str, *, confidence: float | None = None,
                    status: str = "candidate", data: dict[str, Any] | None = None,
                    decision_log_id: str | None = None) -> Any:
        return await self.db.insert("trade_signals", {
            "decision_log_id": decision_log_id,
            "symbol": symbol.upper(),
            "side": side,
            "signal_type": signal_type,
            "confidence": confidence,
            "status": status,
            "signal_data": data or {},
        }, returning=True)

    async def order(self, symbol: str, side: str, quantity: float, status: str, *,
                   order_type: str = "paper_market", price: float | None = None,
                   client_order_id: str | None = None, signal_id: str | None = None,
                   response: dict[str, Any] | None = None) -> Any:
        return await self.db.insert("orders", {
            "signal_id": signal_id,
            "client_order_id": client_order_id,
            "symbol": symbol.upper(),
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "price": price,
            "status": status,
            "exchange_response": response or {"execution_mode": "PAPER"},
        }, returning=True)

    async def position(self, symbol: str, side: str, quantity: float, status: str, *,
                     entry_price: float | None = None, mark_price: float | None = None,
                     stop_loss: float | None = None, take_profit: float | None = None,
                     trailing_stop: float | None = None, trailing_take_profit: float | None = None,
                     data: dict[str, Any] | None = None) -> Any:
        return await self.db.insert("positions", {
            "symbol": symbol.upper(), "side": side, "quantity": quantity,
            "entry_price": entry_price, "mark_price": mark_price,
            "stop_loss": stop_loss, "take_profit": take_profit,
            "trailing_stop_price": trailing_stop,
            "trailing_take_profit_price": trailing_take_profit,
            "status": status, "position_data": data or {},
        }, returning=True)

    async def risk_event(self, event_type: str, *, symbol: str | None = None,
                         position_id: str | None = None, previous: float | None = None,
                         new: float | None = None, details: dict[str, Any] | None = None) -> bool:
        try:
            await self.db.insert("risk_events", {
                "position_id": position_id, "symbol": symbol,
                "event_type": event_type, "previous_value": previous,
                "new_value": new, "details": details or {},
            })
            return True
        except Exception:
            return False

    async def closed_trade(self, symbol: str, side: str, quantity: float, *,
                          entry_price: float | None = None, exit_price: float | None = None,
                          realized_pnl: float | None = None, fees: float | None = None,
                          exit_reason: str | None = None, position_id: str | None = None,
                          trade_data: dict[str, Any] | None = None) -> Any:
        return await self.db.insert("trade_history", {
            "position_id": position_id, "symbol": symbol.upper(), "side": side,
            "quantity": quantity, "entry_price": entry_price, "exit_price": exit_price,
            "realized_pnl": realized_pnl, "fees": fees, "exit_reason": exit_reason,
            "trade_data": trade_data or {},
        }, returning=True)

    async def market_snapshot(self, symbol: str, venue: str, snapshot_type: str,
                             payload: dict[str, Any]) -> bool:
        try:
            await self.db.insert("market_snapshots", {
                "symbol": symbol.upper(), "venue": venue, "snapshot_type": snapshot_type,
                "payload": payload,
            })
            return True
        except Exception:
            return False

    async def metrics(self, window: str, payload: dict[str, Any]) -> bool:
        try:
            await self.db.insert("performance_metrics", {
                "metric_window": window, "metrics": payload,
            })
            return True
        except Exception:
            return False


repository = OrderFlowRepository()
