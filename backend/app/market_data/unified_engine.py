"""Phase 3 exchange-neutral market-data normalization with fail-closed book safety."""
import math
import time
import zlib
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
    # Preserve Delta Exchange's raw numeric strings for checksum verification.
    delta_raw_bids: dict = field(default_factory=dict)
    delta_raw_asks: dict = field(default_factory=dict)
    sequence: int | None = None
    cross_sequence: int | None = None
    synchronized: bool = False
    stale: bool = True
    error: str | None = None
    exchange_ts: int | None = None
    received_ts: int | None = None
    # Monotonic receive time is used for bridged Binance depth freshness.
    received_monotonic: float | None = None

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

    @staticmethod
    def _raw_level_map(levels):
        """Keep original numeric text so exchange CRC checks use exact formatting."""
        result = {}
        for raw_price, raw_quantity in levels:
            price = float(raw_price)
            quantity = float(raw_quantity)
            if quantity > 0:
                result[price] = (str(raw_price), str(raw_quantity))
        return result

    @staticmethod
    def _apply_raw_levels(side, updates):
        for raw_price, raw_quantity in updates:
            price = float(raw_price)
            quantity = float(raw_quantity)
            if quantity == 0:
                side.pop(price, None)
            else:
                side[price] = (str(raw_price), str(raw_quantity))

    @staticmethod
    def _delta_crc32(raw_bids, raw_asks):
        asks = sorted(raw_asks.items(), key=lambda item: item[0])[:10]
        bids = sorted(raw_bids.items(), key=lambda item: item[0], reverse=True)[:10]
        asks_text = ",".join(f"{price}:{quantity}" for _, (price, quantity) in asks)
        bids_text = ",".join(f"{price}:{quantity}" for _, (price, quantity) in bids)
        return zlib.crc32((asks_text + "|" + bids_text).encode("utf-8")) & 0xffffffff

    def _delta_checksum_matches(self, data, raw_bids, raw_asks):
        expected = self.strict_int(data.get("cs"))
        return expected is not None and expected <= 0xffffffff and self._delta_crc32(raw_bids, raw_asks) == expected



    def record_message(self, exchange):
        now = time.time()
        self.last_seen[exchange] = now
        self.counts[exchange] = self.counts.get(exchange, 0) + 1

    def touch_book(self, exchange, book, exchange_ts):
        self.record_message(exchange)
        book.exchange_ts = exchange_ts
        book.received_ts = int(time.time() * 1000)
        book.stale = False

    def _exchange_timestamp_is_fresh(self, timestamp_ms):
        """Reject book events with missing, stale, or implausibly future exchange time."""
        if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int) or timestamp_ms <= 0:
            return False
        age_seconds = time.time() - timestamp_ms / 1000.0
        return math.isfinite(age_seconds) and -5.0 <= age_seconds <= self.stale_after_seconds

    def _invalidate(self, exchange, book, reason):
        book.bids.clear()
        book.asks.clear()
        book.delta_raw_bids.clear()
        book.delta_raw_asks.clear()
        book.synchronized = False
        book.stale = True
        book.received_monotonic = None
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

    def apply_binance_bridge_book(self, payload):
        """Apply a full book published by the separately sequence-validated Binance bridge."""
        if not isinstance(payload, dict):
            return False
        symbol = str(payload.get("symbol") or "").upper()
        if not symbol:
            return False
        book = self.book("binance", symbol)
        if payload.get("synchronized") is not True or payload.get("stale") is True:
            reason = str(payload.get("error") or "Binance depth bridge is unsynchronized or stale")
            self._invalidate("binance", book, reason)
            return True
        sequence = self.strict_int(payload.get("last_update_id"))
        age = payload.get("age_seconds")
        if isinstance(age, bool):
            age = None
        try:
            age_value = float(age)
        except (TypeError, ValueError, OverflowError):
            age_value = float("nan")
        if sequence is None or not math.isfinite(age_value) or age_value < 0 or age_value > self.stale_after_seconds:
            self._invalidate("binance", book, "Invalid or stale Binance bridged snapshot metadata")
            return False
        try:
            bids = self._side_from_levels(self._parse_levels(payload.get("bids", [])))
            asks = self._side_from_levels(self._parse_levels(payload.get("asks", [])))
        except (TypeError, ValueError, OverflowError) as exc:
            self._invalidate("binance", book, "Invalid Binance bridged snapshot levels: " + str(exc))
            return False
        if not self._valid_book(bids, asks):
            self._invalidate("binance", book, "Empty, locked, or crossed Binance bridged snapshot")
            return False
        book.bids = bids
        book.asks = asks
        book.sequence = sequence
        book.cross_sequence = None
        book.synchronized = True
        book.stale = False
        book.error = None
        book.exchange_ts = None
        book.received_ts = int(time.time() * 1000)
        # Preserve the bridge's source age instead of refreshing it at copy time.
        book.received_monotonic = time.monotonic() - age_value
        self.record_message("binance")
        self.errors.pop(self.key("binance", symbol), None)
        return True

    def invalidate_binance_bridge_book(self, symbol, reason):
        """Fail closed when the Binance bridge is disconnected or cannot supply a fresh book."""
        book = self.book("binance", symbol)
        if not book.synchronized and book.error == reason:
            return True
        self._invalidate("binance", book, reason)
        return True

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
        channel_type = str(raw.get("type", raw.get("channel", data.get("type", "")))).lower()
        action = str(data.get("action") or raw.get("action") or channel_type).lower()
        if action == "error":
            message = data.get("msg") or data.get("message") or raw.get("msg") or "Delta order-book stream error"
            return self._invalidate(exchange, book, "Delta order-book stream error: " + str(message))
        is_snapshot = action in ("snapshot", "initial")
        is_update = action in ("update", "delta")
        if not (is_snapshot or is_update):
            return self._invalidate(exchange, book, "Unsupported Delta order-book message; resubscribe to ob_updates")
        raw_bid_levels = data.get("buy", data.get("bids", data.get("b", [])))
        raw_ask_levels = data.get("sell", data.get("asks", data.get("a", [])))
        try:
            bid_levels = self._parse_levels(raw_bid_levels)
            ask_levels = self._parse_levels(raw_ask_levels)
        except (TypeError, ValueError, OverflowError) as exc:
            return self._invalidate(exchange, book, "Invalid Delta order-book levels: " + str(exc))
        sequence = self.strict_int(data.get("seq"))
        if sequence is None:
            return self._invalidate(exchange, book, "Delta order-book sequence is missing or invalid")
        checksum_channel = channel_type == "ob_updates"
        if is_snapshot:
            bids = self._side_from_levels(bid_levels)
            asks = self._side_from_levels(ask_levels)
            raw_bids = self._raw_level_map(raw_bid_levels) if checksum_channel else {}
            raw_asks = self._raw_level_map(raw_ask_levels) if checksum_channel else {}
        else:
            if not book.synchronized or book.sequence is None:
                return self._invalidate(exchange, book, "Delta update arrived before a synchronized snapshot")
            if sequence != book.sequence + 1:
                return self._invalidate(exchange, book, "Delta order-book sequence gap; reconnect for snapshot recovery")
            bids = dict(book.bids)
            asks = dict(book.asks)
            self._apply_levels(bids, bid_levels)
            self._apply_levels(asks, ask_levels)
            raw_bids = dict(book.delta_raw_bids) if checksum_channel else {}
            raw_asks = dict(book.delta_raw_asks) if checksum_channel else {}
            if checksum_channel:
                self._apply_raw_levels(raw_bids, raw_bid_levels)
                self._apply_raw_levels(raw_asks, raw_ask_levels)
        if not self._valid_book(bids, asks):
            return self._invalidate(exchange, book, "Delta update produced an empty, locked, or crossed book")
        if checksum_channel and not self._delta_checksum_matches(data, raw_bids, raw_asks):
            return self._invalidate(exchange, book, "Delta order-book checksum missing, invalid, or mismatched")
        book.bids = bids
        book.asks = asks
        book.delta_raw_bids = raw_bids
        book.delta_raw_asks = raw_asks
        book.sequence = sequence
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
        symbol = str(data.get("sy") or data.get("symbol") or data.get("s") or default_symbol).upper()
        raw_timestamp = raw.get("ts") or raw.get("E") or raw.get("timestamp") or data.get("ts")
        ts = self.as_int(raw_timestamp)
        if ex == "delta" and ts is not None and ts > 10**13:
            ts //= 1000
        book = self.book(ex, symbol)
        is_bybit_book_event = topic.startswith("orderbook.") and raw.get("type") in ("snapshot", "delta")
        delta_action = str(data.get("action") or raw.get("action") or raw.get("type") or "").lower()
        is_delta_book_event = ex == "delta" and delta_action in ("snapshot", "update") and (
            raw.get("type") in ("ob_updates", "snapshot", "delta")
            or data.get("type") in ("ob_updates", "ob_l2")
            or any(k in data for k in ("buy", "sell", "bids", "asks"))
        )
        if (is_bybit_book_event or is_delta_book_event) and not self._exchange_timestamp_is_fresh(ts):
            return self._invalidate(ex, book, "Missing, stale, or future exchange timestamp")
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
            if ex == "delta" and (
                raw.get("type") in ("ob_updates", "ob_l2")
                or data.get("type") in ("ob_updates", "ob_l2")
                or data.get("action") in ("snapshot", "update", "error")
                or any(k in data for k in ("buy", "sell", "bids", "asks"))
            ):
                return self._process_delta_exchange_book(ex, book, raw, data, ts)

            tape = []
            if ex == "binance" and data.get("e") == "aggTrade":
                tape = [data]
            elif topic.startswith("publicTrade"):
                tape = data if isinstance(data, list) else [data]
            elif ex == "delta" and data.get("type") in ("trades", "trade") and ("p" in data or "price" in data) and ("s" in data or "size" in data or "quantity" in data):
                tape = [data]
            for trade_data in tape:
                raw_price = trade_data.get("p", trade_data.get("price", 0))
                raw_quantity = trade_data.get("q", trade_data.get("v", trade_data.get("size", trade_data.get("quantity", trade_data.get("s", 0)))))
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
                buyer_role = str(trade_data.get("r", "")).lower()
                if isinstance(maker, bool):
                    side = "sell" if maker else "buy"
                elif ex == "delta" and buyer_role in ("m", "t"):
                    side = "sell" if buyer_role == "m" else "buy"
                else:
                    side = str(trade_data.get("S", trade_data.get("side", trade_data.get("takerSide", "")))).lower() or None
                if side not in ("buy", "sell"):
                    side = None
                trade_timestamp = self.as_int(trade_data.get("T") or trade_data.get("t") or trade_data.get("timestamp") or ts)
                if ex == "delta" and trade_timestamp is not None and trade_timestamp > 10**13:
                    trade_timestamp //= 1000
                trade = Trade(ex, symbol, price, quantity, side, trade_timestamp, int(time.time() * 1000))
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
        if book.received_monotonic is not None:
            age = time.monotonic() - book.received_monotonic
        else:
            age = None if book.received_ts is None else max(0, time.time() - book.received_ts / 1000)
        stale = (
            age is None or not math.isfinite(age) or age < 0 or age > self.stale_after_seconds
            or not book.synchronized or book.error is not None
        )
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
