"""Async persistence bridge for synchronous paper simulator lifecycle events."""
from __future__ import annotations
import asyncio
import logging
from typing import Any
from app.database.repository import repository

logger = logging.getLogger(__name__)

class PaperPersistenceWorker:
    def __init__(self, repo=repository, queue_size: int = 1000):
        self.repo = repo
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        self.task: asyncio.Task | None = None
        self.running = False
        self.position_ids: dict[str, str] = {}

    def enqueue(self, event: dict[str, Any]) -> bool:
        try:
            self.queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            logger.error("Paper persistence queue full; event dropped (%s)", event.get("type"))
            return False

    async def start(self):
        if self.running:
            return
        self.running = True
        self.task = asyncio.create_task(self._run(), name="paper-persistence-worker")

    async def stop(self):
        self.running = False
        if self.task:
            try:
                await asyncio.wait_for(self.queue.join(), timeout=5)
            except asyncio.TimeoutError:
                logger.error("Paper persistence queue drain timed out")
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _run(self):
        while True:
            event = await self.queue.get()
            try:
                await self._persist(event)
            except Exception:
                logger.exception("Paper lifecycle persistence event failed: %s", event.get("type"))
            finally:
                self.queue.task_done()

    async def _persist(self, e: dict[str, Any]):
        kind = e.get("type")
        if kind == "order_open":
            order = e["order"]; pos = e["position"]
            await self.repo.order(order["symbol"], order["side"], order["quantity"],
                order["status"], order_type="paper_simulated", price=order["entry_price"],
                client_order_id=order["order_id"], response={"paper_only": True, **order})
            result = await self.repo.position(pos["symbol"], pos["side"], pos["quantity"], "OPEN",
                entry_price=pos["entry_price"], mark_price=pos["entry_price"],
                stop_loss=pos.get("stop_loss_price"), take_profit=pos.get("take_profit_price"),
                trailing_stop=pos.get("tsl_price"), trailing_take_profit=pos.get("ttp_price"),
                data=pos)
            if result and isinstance(result, list) and result and result[0].get("id"):
                self.position_ids[pos["symbol"]] = result[0]["id"]
            await self.repo.system_log("INFO", "Paper position opened", "paper_lifecycle",
                {"symbol": pos["symbol"], "position_id": pos.get("position_id")})
        elif kind == "position_mark":
            pos=e["position"]; symbol=pos["symbol"]
            filters={"symbol":f"eq.{symbol}","status":"eq.OPEN"}
            await self.repo.db.update("positions", {
                "mark_price": e["price"], "trailing_stop_price": pos.get("tsl_price"),
                "trailing_take_profit_price": pos.get("ttp_price"), "position_data": pos,
            }, filters=filters)
        elif kind == "management_update":
            pos=e["position"]
            await self.repo.db.update("positions", {
                "stop_loss": pos.get("stop_loss_price"), "take_profit": pos.get("take_profit_price"),
                "trailing_stop_price": pos.get("tsl_price"), "trailing_take_profit_price": pos.get("ttp_price"),
                "position_data": pos,
            }, filters={"symbol":f"eq.{pos['symbol']}","status":"eq.OPEN"})
            await self.repo.risk_event("PAPER_POSITION_MANAGEMENT_UPDATED",symbol=pos["symbol"],
                details={"paper_only":True,"management":pos})
        elif kind == "position_close":
            trade=e["trade"]; symbol=trade["symbol"]
            await self.repo.db.update("positions", {
                "status":"CLOSED","mark_price":trade["exit_price"],"closed_at":e["closed_at"],
                "position_data":{"close_reason":trade["close_reason"],"paper_only":True},
            }, filters={"symbol":f"eq.{symbol}","status":"eq.OPEN"})
            await self.repo.closed_trade(symbol,trade["side"],trade["quantity"],
                entry_price=trade["entry_price"],exit_price=trade["exit_price"],
                realized_pnl=trade["net_pnl"],fees=trade["entry_fee"]+trade["exit_fee"],
                exit_reason=trade["close_reason"],trade_data=trade)
            await self.repo.system_log("INFO","Paper position closed","paper_lifecycle",
                {"symbol":symbol,"close_reason":trade["close_reason"],"net_pnl":trade["net_pnl"]})
            logger.info("Persisted paper close for %s", symbol)
        else:
            logger.warning("Unknown paper persistence event type: %s", kind)
