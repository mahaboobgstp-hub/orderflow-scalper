from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class LocalOrderBook:
    symbol: str
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    last_update_id: int = 0
    synchronized: bool = False
    update_count: int = 0

    def load_snapshot(self, snapshot: dict) -> None:
        self.bids = {
            float(price): float(quantity)
            for price, quantity in snapshot.get("bids", [])
            if float(quantity) > 0
        }
        self.asks = {
            float(price): float(quantity)
            for price, quantity in snapshot.get("asks", [])
            if float(quantity) > 0
        }
        self.last_update_id = int(snapshot["lastUpdateId"])
        self.synchronized = True
        self.update_count = 0

    def _apply_levels(
        self,
        book_side: dict[float, float],
        updates: Iterable[list[str]],
    ) -> None:
        for price_text, quantity_text in updates:
            price = float(price_text)
            quantity = float(quantity_text)

            if quantity == 0:
                book_side.pop(price, None)
            else:
                book_side[price] = quantity

    def apply_diff(self, event: dict) -> bool:
        if not self.synchronized:
            return False

        first_update_id = int(event["U"])
        final_update_id = int(event["u"])

        # Ignore events already represented in our local book.
        if final_update_id <= self.last_update_id:
            return True

        # A missing update means our local book may be incorrect.
        if first_update_id > self.last_update_id + 1:
            self.synchronized = False
            return False

        self._apply_levels(self.bids, event.get("b", []))
        self._apply_levels(self.asks, event.get("a", []))

        self.last_update_id = final_update_id
        self.update_count += 1
        return True

    def view(self, levels: int = 10) -> dict:
        best_bids = sorted(
            self.bids.items(),
            key=lambda item: item[0],
            reverse=True,
        )[:levels]

        best_asks = sorted(
            self.asks.items(),
            key=lambda item: item[0],
        )[:levels]

        best_bid = best_bids[0][0] if best_bids else None
        best_ask = best_asks[0][0] if best_asks else None

        bid_quantity = sum(quantity for _, quantity in best_bids)
        ask_quantity = sum(quantity for _, quantity in best_asks)
        total_quantity = bid_quantity + ask_quantity

        imbalance = (
            (bid_quantity - ask_quantity) / total_quantity
            if total_quantity > 0
            else 0.0
        )

        spread = (
            best_ask - best_bid
            if best_bid is not None and best_ask is not None
            else None
        )

        return {
            "symbol": self.symbol,
            "synchronized": self.synchronized,
            "last_update_id": self.last_update_id,
            "update_count": self.update_count,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "bid_quantity_top_levels": bid_quantity,
            "ask_quantity_top_levels": ask_quantity,
            "book_imbalance": imbalance,
            "bids": [
                {"price": price, "quantity": quantity}
                for price, quantity in best_bids
            ],
            "asks": [
                {"price": price, "quantity": quantity}
                for price, quantity in best_asks
            ],
        }
