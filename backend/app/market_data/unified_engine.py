"""Phase 3 exchange-neutral market-data normalization with fail-closed book safety."""
import math
import time
from dataclasses import dataclass, field


@dataclass
class Trade:
    exchange: str
    symbol: str
    price: float
    quantity: float
    side: str | None
    exchange_ts: int | None
    received_ts: int


@dataclass
class Book:
    exchange: str
    symbol: str
    bids: dict = field(default_factory=dict)
    asks: dict = field(default_factory=dict)
    sequence: int | None = None
    cross_sequence: int | None = None
    synchronized: bool = False
    stale: bool = True
    error: str | None = None
    exchange_ts: int | None = None
    received_ts: int | None = None

    def best_bid(self):
        return max(self.bids) if self.bids else None

    def best_ask(self):
        return min(self.asks) if self.asks else None


class UnifiedMarketDataEngine:
    def __init__(self, stale_after_seconds=3.0, max_levels=200):
        self.stale_after_seconds = max(0.1, float(stale_after_seconds))
        self.max_levels = max(1, int(max_levels))
        self.books = {}
        self.trades = {}
        self.counts = {}
        self.last_seen = {}
        self.errors = {}

    @staticmethod
    def key(exchange, symbol):
        return exchange.lower() + ":" + symbol.upper()

    def book(self, exchange, symbol):
        key = self.key(exchange, symbol)
        if key not in self.books:
            self.books[key] = Book(exchange.lower(), symbol.upper())
        return self.books[key]

    @staticmethod
    def strict_int(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return None

    @classmethod
    def as_int(cls, value):
        return cls.strict_int(value)

    @staticmethod
    def _parse_levels(levels):
        if levels is None:
            return []
        if not isinstance(levels, (list, tuple)):
            raise ValueError("Depth levels must be a list.")
        parsed = []
        for row in levels:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                raise ValueError("Depth level must contain price and quantity.")
            raw_price, raw_quantity = row
            if isinstance(raw_price, bool) or isinstance(raw_quantity, bool):
                raise ValueError("Depth level values cannot be boolean.")
            try:
                price = float(raw_price)
                quantity = float(raw_quantity)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Depth level values must be numeric.") from exc
            if not math.isfinite(price) or price <= 0:
                raise ValueError("Depth price must be positive and finite.")
            if not math.isfinite(quantity) or quantity < 0:
                raise ValueError("Depth quantity must be non-negative and finite.")
            parsed.append((price, quantity))
        return parsed

    @staticmethod
    def _side_from_levels(levels):
        return {price: quantity for price, quantity in levels if quantity > 0}

    @staticmethod
    def _apply_levels(side, updates):
        for price, quantity in updates:
            if quantity == 0:
                side.pop(price, None)
            else:
                side[price] = quantity

    @staticmethod
    def _valid_book(bids, asks):
        return bool(bids and asks and max(bids) < min(asks))

    def record_message(self, exchange):
        now = time.time()
        self.last_seen[exchange] = now
        self.counts[exchange] = self.counts.get(exchange, 0) + 1

    def touch_book(self, exchange, book, exchange_ts):
        self.record_message(exchange)
        book.exchange_ts = exchange_ts
        book.received_ts = int(time.time() * 1000)
        book.stale = False

    def _invalidate(self, exchange, book, reason):
        book.bids.clear()
        book.asks.clear()
        book.synchronized = False
        book.stale = True
        book.error = reason
        key = self.key(exchange, book.symbol)
        self.errors[key] = reason
        self.record_message(exchange)
        return {
            "type": "book_invalid",
            "synchronized": False,
            "resync_required": True,
            "error": reason,
        }

    def _apply_bybit_snapshot(self, exchange, book, data, exchange_ts):
        update_id = self.strict_int(data.get("u"))
        cross_seq = self.strict_int(data.get("seq")) if data.get("seq") is not None else None
        if update_id is None or (data.get("seq") is not None and cross_seq is None):
            return self._invalidate(exchange, book, "Invalid Bybit snapshot sequence")
        try:
            bids = self._side_from_levels(self._parse_levels(data.get("b", [])))
            asks = self._side_from_levels(self._parse_levels(data.get("a", [])))
        except (TypeError, ValueError, OverflowError) as exc:
            return self._invalidate(exchange, book, "Invalid Bybit snapshot levels: " + str(exc))
        if not self._valid_book(bids, asks):
            return self._invalidate(exchange, book, "Empty, locked, or crossed Bybit snapshot")
        book.bids = bids
        book.asks = asks
        book.sequence = update_id
        book.cross_sequence = cross_seq
        book.synchronized = True
        book.stale = False
        book.error = None
        self.errors.pop(self.key(exchange, book.symbol), None)
        self.touch_book(exchange, book, exchange_ts)
        return {"type": "book_snapshot", "synchronized": True, "resync_required": False}

    def _apply_bybit_delta(self, exchange, book, data, exchange_ts):
        update_id = self.strict_int(data.get("u"))
        cross_seq = self.strict_int(data.get("seq")) if data.get("seq") is not None else None
        if update_id is None or (data.get("seq") is not None and cross_seq is None):
            return self._invalidate(exchange, book, "Invalid Bybit delta sequence")
        if update_id == 1:
            return self._invalidate(exchange, book, "Bybit update ID reset; fresh snapshot required")
        if not book.synchronized or book.sequence is None:
            return self._invalidate(exchange, book, "Bybit delta arrived before a synchronized snapshot")
        if update_id <= book.sequence:
            self.record_message(exchange)
            return {"type": "book_delta_ignored", "synchronized": book.synchronized, "resync_required": False}
        if update_id != book.sequence + 1:
            return self._invalidate(exchange, book, "Bybit order-book update ID gap; reconnect for snapshot recovery")
        if cross_seq is not None and book.cross_sequence is not None and cross_seq < book.cross_sequence:
            return self._invalidate(exchange, book, "Bybit cross-sequence regression")

        try:
            bid_updates = self._parse_levels(data.get("b", []))
            ask_updates = self._parse_levels(data.get("a", []))
        except (TypeError, ValueError, OverflowError) as exc:
            return self._invalidate(exchange, book, "Invalid Bybit delta levels: " + str(exc))

        next_bids = dict(book.bids)
        next_asks = dict(book.asks)
        self._apply_levels(next_bids, bid_updates)
        self._apply_levels(next_asks, ask_updates)
        if not self._valid_book(next_bids, next_asks):
            return self._invalidate(exchange, book, "Bybit delta produced an empty, locked, or crossed book")
        book.bids = next_bids
        book.asks = next_asks
        book.sequence = update_id
        if cross_seq is not None:
            book.cross_sequence = cross_seq
        book.synchronized = True
        book.stale = False
        book.error = None
        self.errors.pop(self.key(exchange, book.symbol), None)
        self.touch_book(exchange, book, exchange_ts)
        return {"type": "book_delta", "synchronized": True, "resync_required": False}

    def _process_delta_exchange_book(self, exchange, book, raw, data, exchange_ts):
        typ = str(raw.get("type", raw.get("channel", data.get("action", "")))).lower()
        is_snapshot = typ in ("snapshot", "initial")
        try:
            bid_levels = self._parse_levels(data.get("buy", data.get("bids", [])))
            ask_levels = self._parse_levels(data.get("sell", data.get("asks", [])))
        except (TypeError, ValueError, OverflowError) as exc:
            return self._invalidate(exchange, book, "Invalid Delta order-book levels: " + str(exc))
        if is_snapshot:
            bids = self._side_from_levels(bid_levels)
            asks = self._side_from_levels(ask_levels)
        else:
            if not book.synchronized:
                return self._invalidate(exchange, book, "Delta update arrived before a synchronized snapshot")
            bids = dict(book.bids)
            asks = dict(book.asks)
            self._apply_levels(bids, bid_levels)
            self._apply_levels(asks, ask_levels)
        if not self._valid_book(bids, asks):
            return self._invalidate(exchange, book, "Delta update produced an empty, locked, or crossed book")
        book.bids = bids
        book.asks = asks
        if is_snapshot:
            book.sequence = self.strict_int(data.get("u"))
        book.synchronized = True
        book.stale = False
        book.error = None
        self.errors.pop(self.key(exchange, book.symbol), None)
        self.touch_book(exchange, book, exchange_ts)
        return {"type": "book_snapshot" if is_snapshot else "book_delta", "synchronized": True, "resync_required": False}

    def process(self, exchange, raw, default_symbol="BTCUSDT"):
        ex = exchange.lower()
        if not isinstance(raw, dict):
            return None
        topic = raw.get("topic", "")
        data = raw.get("data", raw)
        if isinstance(data, list) and topic.startswith("publicTrade"):
            result = None
            for item in data:
                if isinstance(item, dict):
                    result = self.process(ex, {"topic": topic, "data": item, "ts": raw.get("ts")}, default_symbol) or result
            return result
        if not isinstance(data, dict):
            return None
        symbol = str(data.get("s") or data.get("symbol") or default_symbol).upper()
        ts = self.as_int(raw.get("ts") or raw.get("E") or raw.get("timestamp") or data.get("ts"))
        book = self.book(ex, symbol)
        try:
            # Binance public depth diffs do not have a REST bridge in this
            # exchange-neutral path; never expose these partial levels as a book.
            if ex == "binance" and ("b" in data or "a" in data) and ("U" in data or "u" in data):
                book.bids.clear()
                book.asks.clear()
                book.synchronized = False
                book.stale = True
                book.error = "Needs REST snapshot synchronization"
                update_id = self.strict_int(data.get("u"))
                if update_id is not None:
                    book.sequence = update_id
                self.record_message(ex)
                self.errors[self.key(ex, symbol)] = book.error
                return {"type": "book_delta", "synchronized": False, "resync_required": False}
            if topic.startswith("orderbook."):
                typ = str(raw.get("type", "")).lower()
                if typ == "snapshot":
                    return self._apply_bybit_snapshot(ex, book, data, ts)
                if typ == "delta":
                    return self._apply_bybit_delta(ex, book, data, ts)
                return None
            if ex == "delta" and any(k in data for k in ("buy", "sell", "bids", "asks")):
                return self._process_delta_exchange_book(ex, book, raw, data, ts)

            tape = []
            if ex == "binance" and data.get("e") == "aggTrade":
                tape = [data]
            elif topic.startswith("publicTrade"):
                tape = data if isinstance(data, list) else [data]
            elif ex == "delta" and "price" in data and ("size" in data or "quantity" in data):
                tape = [data]
            for trade_data in tape:
                raw_price = trade_data.get("p", trade_data.get("price", 0))
                raw_quantity = trade_data.get("q", trade_data.get("v", trade_data.get("size", trade_data.get("quantity", 0))))
                if isinstance(raw_price, bool) or isinstance(raw_quantity, bool):
                    self.record_message(ex)
                    continue
                try:
                    price = float(raw_price)
                    quantity = float(raw_quantity)
                except (TypeError, ValueError, OverflowError):
                    self.record_message(ex)
                    continue
                if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0:
                    self.record_message(ex)
                    continue
                maker = trade_data.get("m")
                side = ("sell" if maker else "buy") if isinstance(maker, bool) else str(trade_data.get("S", trade_data.get("side", trade_data.get("takerSide", "")))).lower() or None
                if side not in ("buy", "sell"):
                    side = None
                trade = Trade(ex, symbol, price, quantity, side, self.as_int(trade_data.get("T") or trade_data.get("timestamp") or ts), int(time.time() * 1000))
                key = self.key(ex, symbol)
                self.trades.setdefault(key, []).append(trade)
                self.trades[key] = self.trades[key][-5000:]
                # Trades are not book updates: they must not reset book age.
                self.record_message(ex)
                return {"type": "trade", "exchange": ex, "symbol": symbol, "price": price, "quantity": quantity, "side": side}
        except (ValueError, TypeError, KeyError) as err:
            book.error = "Payload parse error: " + str(err)
            self.errors[self.key(ex, symbol)] = book.error
            self.record_message(ex)
            return {"type": "parse_error", "error": book.error}
        return None

    def get_book(self, exchange, symbol):
        book = self.books.get(self.key(exchange, symbol))
        if book is None:
            return None
        age = None if book.received_ts is None else max(0, time.time() - book.received_ts / 1000)
        stale = age is None or age > self.stale_after_seconds or not book.synchronized or book.error is not None
        book.stale = stale
        bids = sorted(book.bids.items(), reverse=True)[:self.max_levels]
        asks = sorted(book.asks.items())[:self.max_levels]
        return {
            "exchange": book.exchange, "symbol": book.symbol,
            "bids": [[p, q] for p, q in bids], "asks": [[p, q] for p, q in asks],
            "best_bid": book.best_bid(), "best_ask": book.best_ask(),
            "spread": book.best_ask() - book.best_bid() if book.best_bid() is not None and book.best_ask() is not None else None,
            "sequence": book.sequence, "cross_sequence": book.cross_sequence,
            "exchange_timestamp_ms": book.exchange_ts, "received_timestamp_ms": book.received_ts,
            "synchronized": book.synchronized, "stale": stale,
            "age_seconds": round(age, 3) if age is not None else None, "integrity_error": book.error,
        }

    def get_recent_trades(self, exchange, symbol, limit=100):
        records = self.trades.get(self.key(exchange, symbol), [])[-max(1, min(int(limit), 500)):]
        return [
            {"exchange": trade.exchange, "symbol": trade.symbol, "price": trade.price, "quantity": trade.quantity, "side": trade.side,
             "exchange_timestamp_ms": trade.exchange_ts, "received_timestamp_ms": trade.received_ts}
            for trade in records
        ]

    def get_status(self):
        now = time.time()
        exchanges = sorted(set(self.counts) | {book.exchange for book in self.books.values()})
        books = {}
        for key, book in self.books.items():
            age = None if book.received_ts is None else max(0.0, now - book.received_ts / 1000)
            stale = age is None or age > self.stale_after_seconds or not book.synchronized or book.error is not None
            book.stale = stale
            bids = sorted(book.bids.items(), reverse=True)[:10]
            asks = sorted(book.asks.items())[:10]
            bid_depth = sum(q for _, q in bids)
            ask_depth = sum(q for _, q in asks)
            books[key] = {
                "synchronized": book.synchronized, "stale": stale, "integrity_error": book.error,
                "sequence": book.sequence, "cross_sequence": book.cross_sequence,
                "age_seconds": round(age, 3) if age is not None else None,
                "best_bid": book.best_bid(), "best_ask": book.best_ask(),
                "spread": book.best_ask() - book.best_bid() if book.best_ask() is not None and book.best_bid() is not None else None,
                "bid_depth_top10": bid_depth, "ask_depth_top10": ask_depth,
                "imbalance_top10": (bid_depth - ask_depth) / (bid_depth + ask_depth) if bid_depth + ask_depth else None,
                "received_timestamp_ms": book.received_ts, "exchange_timestamp_ms": book.exchange_ts,
            }
        return {
            "phase": 3, "engine": "unified_market_data", "stale_after_seconds": self.stale_after_seconds,
            "exchanges": {exchange: {"messages_received": self.counts.get(exchange, 0), "last_message_age_seconds": round(now - self.last_seen[exchange], 3) if exchange in self.last_seen else None} for exchange in exchanges},
            "books": books, "trade_streams": {key: len(value) for key, value in self.trades.items()}, "errors": self.errors.copy(),
        }
