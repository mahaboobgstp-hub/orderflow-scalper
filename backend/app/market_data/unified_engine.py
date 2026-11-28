"""Phase 3 exchange-neutral market-data normalization."""
import time
import math
import re
from dataclasses import dataclass, field

@dataclass
class Trade:
    exchange:str; symbol:str; price:float; quantity:float; side:str|None
    exchange_ts:int|None; received_ts:int

@dataclass
class Book:
    exchange:str; symbol:str; bids:dict=field(default_factory=dict); asks:dict=field(default_factory=dict)
    sequence:int|None=None; synchronized:bool=False; stale:bool=True; error:str|None=None
    exchange_ts:int|None=None; received_ts:int|None=None
    def best_bid(self): return max(self.bids) if self.bids else None
    def best_ask(self): return min(self.asks) if self.asks else None

class UnifiedMarketDataEngine:
    def __init__(self, stale_after_seconds=3.0, max_levels=200):
        if isinstance(max_levels, bool) or not isinstance(max_levels, int) or max_levels < 1:
            raise ValueError("max_levels must be a positive integer")
        try:
            stale_cutoff = float(stale_after_seconds)
        except (TypeError, ValueError, OverflowError):
            stale_cutoff = 3.0
        if isinstance(stale_after_seconds, bool) or not math.isfinite(stale_cutoff) or stale_cutoff <= 0:
            stale_cutoff = 3.0
        self.stale_after_seconds = max(0.1, stale_cutoff)
        self.max_levels=max_levels
        self.books={}; self.trades={}; self.counts={}; self.last_seen={}; self.feed_counts={}; self.feed_last_seen={}; self.errors={}; self.invalid_symbol_message_count=0
    @staticmethod
    def key(exchange,symbol): return exchange.lower()+":"+symbol.upper()

    @staticmethod
    def normalize_symbol(value):
        if not isinstance(value, str):
            return None
        symbol = value.strip().upper()
        if not symbol or len(symbol) > 32 or not re.fullmatch(r"[A-Z0-9][A-Z0-9._/-]{0,31}", symbol):
            return None
        return symbol

    @classmethod
    def topic_symbol(cls, topic):
        if not isinstance(topic, str):
            return None
        if topic.startswith("publicTrade."):
            candidate = topic.split(".", 1)[1]
        elif topic.startswith("orderbook."):
            candidate = topic.rsplit(".", 1)[-1]
        else:
            return None
        return cls.normalize_symbol(candidate)

    def resolve_symbol(self, data, topic, default_symbol):
        raw_symbol = data.get("s")
        if raw_symbol is None or raw_symbol == "":
            raw_symbol = data.get("symbol"
            )
        explicit_symbol = None
        if raw_symbol is not None and raw_symbol != "":
            explicit_symbol = self.normalize_symbol(raw_symbol)
            if explicit_symbol is None:
                return None

        topic_has_symbol = isinstance(topic, str) and (
            topic.startswith("publicTrade.") or topic.startswith("orderbook.")
        )
        topic_symbol = self.topic_symbol(topic)
        if topic_has_symbol and topic_symbol is None:
            return None
        if explicit_symbol and topic_symbol and explicit_symbol != topic_symbol:
            return None
        return explicit_symbol or topic_symbol or self.normalize_symbol(default_symbol)

    def book(self,exchange,symbol):
        key=self.key(exchange,symbol)
        if key not in self.books: self.books[key]=Book(exchange.lower(),symbol.upper())
        return self.books[key]
    @staticmethod
    def parse_levels(levels):
        if not isinstance(levels, list):
            return None
        parsed = []
        for row in levels:
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                return None
            if isinstance(row[0], bool) or isinstance(row[1], bool):
                return None
            try:
                price, quantity = float(row[0]), float(row[1])
            except (TypeError, ValueError, OverflowError):
                return None
            if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity < 0:
                return None
            parsed.append((price, quantity))
        return parsed

    @staticmethod
    def apply_parsed(side, levels):
        for price, quantity in levels:
            if quantity == 0:
                side.pop(price, None)
            else:
                side[price] = quantity

    @classmethod
    def apply(cls, side, levels):
        parsed = cls.parse_levels(levels)
        if parsed is None:
            return False
        candidate = side.copy()
        cls.apply_parsed(candidate, parsed)
        side.clear()
        side.update(candidate)
        return True

    @staticmethod
    def as_int(x):
        if isinstance(x, bool):
            return None
        if isinstance(x, int):
            return x
        if isinstance(x, float):
            if not math.isfinite(x) or not x.is_integer():
                return None
            return int(x)
        if isinstance(x, str):
            value = x.strip()
            if not value or not value.lstrip("-").isdigit():
                return None
            try:
                return int(value)
            except ValueError:
                return None
        return None

    def invalidate_book(self, exchange, book, reason):
        book.synchronized = False
        book.stale = True
        book.error = reason
        self.errors[self.key(exchange, book.symbol)] = reason

    def trim_side(self, side, *, bids):
        """Keep only the nearest configured price levels (best bids/asks)."""
        if len(side) <= self.max_levels:
            return side
        return dict(sorted(side.items(), reverse=bids)[:self.max_levels])

    def update_book(self, book, bid_levels, ask_levels, snapshot=False):
        parsed_bids = self.parse_levels(bid_levels)
        parsed_asks = self.parse_levels(ask_levels)
        if parsed_bids is None or parsed_asks is None:
            self.invalidate_book(book.exchange, book, "Malformed depth levels")
            return False
        if not snapshot and not book.synchronized:
            self.invalidate_book(book.exchange, book, "Delta received before synchronized snapshot")
            return False
        if not snapshot and not parsed_bids and not parsed_asks:
            self.invalidate_book(book.exchange, book, "Empty depth update")
            return False

        bids = {} if snapshot else book.bids.copy()
        asks = {} if snapshot else book.asks.copy()
        self.apply_parsed(bids, parsed_bids)
        self.apply_parsed(asks, parsed_asks)
        if not bids or not asks:
            self.invalidate_book(book.exchange, book, "Depth update would empty a book side")
            return False
        if max(bids) >= min(asks):
            self.invalidate_book(book.exchange, book, "Crossed or locked order book")
            return False

        # Bound retained depth per side while preserving the best price levels.
        bids = self.trim_side(bids, bids=True)
        asks = self.trim_side(asks, bids=False)
        book.bids, book.asks = bids, asks
        if snapshot:
            book.synchronized = True
        book.error = None
        book.stale = False
        self.errors.pop(self.key(book.exchange, book.symbol), None)
        return True

    def touch_message(self, ex, ts, symbol=None):
        now = time.time()
        self.last_seen[ex] = now
        self.counts[ex] = self.counts.get(ex, 0) + 1
        if symbol is not None:
            feed_key = self.key(ex, symbol)
            self.feed_counts[feed_key] = self.feed_counts.get(feed_key, 0) + 1
            self.feed_last_seen[feed_key] = now
        return now

    def touch(self, ex, b, ts):
        now = self.touch_message(ex, ts, b.symbol)
        b.exchange_ts = ts
        b.received_ts = int(now * 1000)
        b.stale = False

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
                    result = self.process(ex, {"topic": topic, "data": item}, default_symbol) or result
            return result
        if not isinstance(data, dict):
            return None
        symbol = self.resolve_symbol(data, topic, default_symbol)
        if symbol is None:
            self.invalid_symbol_message_count += 1
            return None
        ts = self.as_int(raw.get("ts") or raw.get("E") or raw.get("timestamp") or data.get("ts"))
        book = self.book(ex, symbol)
        try:
            # Binance diffs without the REST snapshot bridge are never applied here.
            if ex == "binance" and ("b" in data or "a" in data) and ("U" in data or "u" in data):
                self.invalidate_book(ex, book, "Needs REST snapshot synchronization")
                self.touch_message(ex, ts, symbol)
                return {"type": "book_delta", "synchronized": False, "error": book.error}

            if topic.startswith("orderbook."):
                typ = str(raw.get("type", "")).lower()
                sequence = self.as_int(data.get("u"))
                if sequence is None or sequence < 0:
                    self.invalidate_book(ex, book, "Invalid order-book sequence")
                    self.touch_message(ex, ts, symbol)
                    return {"type": "parse_error", "error": book.error}
                if typ == "snapshot":
                    valid = self.update_book(book, data.get("b", []), data.get("a", []), snapshot=True)
                elif typ == "delta":
                    if not book.synchronized or book.sequence is None:
                        self.invalidate_book(ex, book, "Delta received before synchronized snapshot")
                        valid = False
                    elif sequence <= book.sequence:
                        self.invalidate_book(ex, book, "Non-progressing order-book sequence")
                        valid = False
                    else:
                        valid = self.update_book(book, data.get("b", []), data.get("a", []), snapshot=False)
                else:
                    return None
                if valid:
                    book.sequence = sequence
                    self.touch(ex, book, ts)
                else:
                    self.touch_message(ex, ts, symbol)
                return {"type": "book_" + typ, "synchronized": book.synchronized, "error": book.error}

            if ex == "delta" and any(k in data for k in ("buy", "sell", "bids", "asks")):
                typ = str(raw.get("type", raw.get("channel", data.get("action", "")))).lower()
                snapshot = typ in ("snapshot", "initial")
                valid = self.update_book(
                    book,
                    data.get("buy", data.get("bids", [])),
                    data.get("sell", data.get("asks", [])),
                    snapshot=snapshot,
                )
                if valid:
                    sequence = self.as_int(data.get("u"))
                    if sequence is not None and sequence >= 0:
                        book.sequence = sequence
                    self.touch(ex, book, ts)
                else:
                    self.touch_message(ex, ts, symbol)
                return {"type": "book_snapshot" if snapshot else "book_delta", "synchronized": book.synchronized, "error": book.error}

            tape = []
            if ex == "binance" and data.get("e") == "aggTrade":
                tape = [data]
            elif topic.startswith("publicTrade"):
                tape = data if isinstance(data, list) else [data]
            elif ex == "delta" and "price" in data and ("size" in data or "quantity" in data):
                tape = [data]
            for trade_data in tape:
                price_raw = trade_data.get("p", trade_data.get("price", 0))
                quantity_raw = trade_data.get("q", trade_data.get("v", trade_data.get("size", trade_data.get("quantity", 0))))
                if isinstance(price_raw, bool) or isinstance(quantity_raw, bool):
                    continue
                try:
                    price, quantity = float(price_raw), float(quantity_raw)
                except (TypeError, ValueError, OverflowError):
                    continue
                if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0:
                    continue
                maker = trade_data.get("m")
                side = ("sell" if maker else "buy") if isinstance(maker, bool) else str(
                    trade_data.get("S", trade_data.get("side", trade_data.get("takerSide", "")))
                ).lower() or None
                if side not in ("buy", "sell"):
                    side = None
                trade = Trade(
                    ex, symbol, price, quantity, side,
                    self.as_int(trade_data.get("T") or trade_data.get("timestamp") or ts),
                    int(time.time() * 1000),
                )
                key = self.key(ex, symbol)
                self.trades.setdefault(key, []).append(trade)
                self.trades[key] = self.trades[key][-5000:]
                self.touch_message(ex, ts, symbol)
                return {"type": "trade", "exchange": ex, "symbol": symbol, "price": price, "quantity": quantity, "side": side}
        except (ValueError, TypeError, KeyError, OverflowError) as err:
            self.invalidate_book(ex, book, "Payload parse error: " + str(err))
            self.touch_message(ex, ts, symbol)
            return {"type": "parse_error", "error": book.error}
        return None
    def get_book(self,exchange,symbol):
        b=self.books.get(self.key(exchange,symbol))
        if b is None:return None
        age=None if b.received_ts is None else max(0,time.time()-b.received_ts/1000)
        stale=not b.synchronized or b.error is not None or age is None or age>self.stale_after_seconds; b.stale=stale
        bids=sorted(b.bids.items(),reverse=True)[:self.max_levels]; asks=sorted(b.asks.items())[:self.max_levels]
        return {"exchange":b.exchange,"symbol":b.symbol,"bids":[[p,q] for p,q in bids],"asks":[[p,q] for p,q in asks],
          "best_bid":b.best_bid(),"best_ask":b.best_ask(),"spread":b.best_ask()-b.best_bid() if b.best_bid() is not None and b.best_ask() is not None else None,
          "sequence":b.sequence,"exchange_timestamp_ms":b.exchange_ts,"received_timestamp_ms":b.received_ts,
          "synchronized":b.synchronized,"stale":stale,"age_seconds":round(age,3) if age is not None else None,"integrity_error":b.error}
    def get_recent_trades(self,exchange,symbol,limit=100):
        records=self.trades.get(self.key(exchange,symbol),[])[-max(1,min(int(limit),500)):]
        return [{"exchange":t.exchange,"symbol":t.symbol,"price":t.price,"quantity":t.quantity,"side":t.side,
          "exchange_timestamp_ms":t.exchange_ts,"received_timestamp_ms":t.received_ts} for t in records]
    def get_status(self):
        now=time.time()
        exchanges=sorted(set(self.counts)|{b.exchange for b in self.books.values()})
        books={}
        for key,b in self.books.items():
            age=None if b.received_ts is None else max(0.0,now-b.received_ts/1000)
            bids=sorted(b.bids.items(),reverse=True)[:10]
            asks=sorted(b.asks.items())[:10]
            bid_depth=sum(q for _,q in bids); ask_depth=sum(q for _,q in asks)
            books[key]={"synchronized":b.synchronized,"stale":not b.synchronized or b.error is not None or age is None or age>self.stale_after_seconds,
              "integrity_error":b.error,"sequence":b.sequence,"age_seconds":round(age,3) if age is not None else None,
              "best_bid":b.best_bid(),"best_ask":b.best_ask(),
              "spread":b.best_ask()-b.best_bid() if b.best_ask() is not None and b.best_bid() is not None else None,
              "bid_depth_top10":bid_depth,"ask_depth_top10":ask_depth,
              "imbalance_top10":(bid_depth-ask_depth)/(bid_depth+ask_depth) if bid_depth+ask_depth else None,
              "received_timestamp_ms":b.received_ts,"exchange_timestamp_ms":b.exchange_ts}
        feeds={key:{"exchange":key.split(":",1)[0],"symbol":key.split(":",1)[1],
              "messages_received":self.feed_counts.get(key,0),
              "last_message_age_seconds":round(now-self.feed_last_seen[key],3) if key in self.feed_last_seen else None}
              for key in sorted(self.feed_counts)}
        return {"phase":3,"engine":"unified_market_data","stale_after_seconds":self.stale_after_seconds,
          "exchanges":{x:{"messages_received":self.counts.get(x,0),"last_message_age_seconds":round(now-self.last_seen[x],3) if x in self.last_seen else None} for x in exchanges},
          "feeds":feeds,"books":books,"trade_streams":{k:len(v) for k,v in self.trades.items()},"errors":self.errors.copy(),
          "invalid_symbol_message_count":self.invalid_symbol_message_count}
