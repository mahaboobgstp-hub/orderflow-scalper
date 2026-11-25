"""Phase 3 exchange-neutral market-data normalization."""
import time
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
        self.stale_after_seconds=stale_after_seconds; self.max_levels=max_levels
        self.books={}; self.trades={}; self.counts={}; self.last_seen={}; self.errors={}
    @staticmethod
    def key(exchange,symbol): return exchange.lower()+":"+symbol.upper()
    def book(self,exchange,symbol):
        key=self.key(exchange,symbol)
        if key not in self.books: self.books[key]=Book(exchange.lower(),symbol.upper())
        return self.books[key]
    @staticmethod
    def apply(side,levels):
        if not isinstance(levels,list): return
        for row in levels:
            try: p,q=float(row[0]),float(row[1])
            except (TypeError,ValueError,IndexError): continue
            if p<=0 or q<0: continue
            if q==0: side.pop(p,None)
            else: side[p]=q
    @staticmethod
    def as_int(x):
        try: return int(x)
        except (ValueError,TypeError): return None
    def touch(self,ex,b,ts):
        now=time.time(); b.exchange_ts=ts; b.received_ts=int(now*1000); b.stale=False
        self.last_seen[ex]=now; self.counts[ex]=self.counts.get(ex,0)+1
    def process(self,exchange,raw,default_symbol="BTCUSDT"):
        ex=exchange.lower()
        if not isinstance(raw,dict): return None
        topic=raw.get("topic",""); data=raw.get("data",raw)
        if isinstance(data,list) and topic.startswith("publicTrade"):
            result=None
            for item in data:
                if isinstance(item,dict): result=self.process(ex,{"topic":topic,"data":item},default_symbol) or result
            return result
        if not isinstance(data,dict): return None
        symbol=str(data.get("s") or data.get("symbol") or default_symbol).upper()
        ts=self.as_int(raw.get("ts") or raw.get("E") or raw.get("timestamp") or data.get("ts"))
        b=self.book(ex,symbol)
        try:
            # Binance depth diffs lack the snapshot bridge here: mark unusable for strategies.
            if ex=="binance" and ("b" in data or "a" in data) and ("U" in data or "u" in data):
                u=self.as_int(data.get("u")); b.sequence=u if u is not None else b.sequence
                self.apply(b.bids,data.get("b",[])); self.apply(b.asks,data.get("a",[]))
                b.synchronized=False; b.error="Needs REST snapshot synchronization"
                self.touch(ex,b,ts); return {"type":"book_delta","synchronized":False}
            if topic.startswith("orderbook."):
                typ=str(raw.get("type","")).lower()
                if typ=="snapshot":
                    b.bids.clear(); b.asks.clear(); self.apply(b.bids,data.get("b",[])); self.apply(b.asks,data.get("a",[]))
                    b.synchronized=bool(b.bids and b.asks); b.error=None if b.synchronized else "Empty snapshot"
                elif typ=="delta":
                    self.apply(b.bids,data.get("b",[])); self.apply(b.asks,data.get("a",[]))
                    b.synchronized=b.synchronized and b.error is None
                b.sequence=self.as_int(data.get("u")) or b.sequence
                self.touch(ex,b,ts); return {"type":"book_"+typ,"synchronized":b.synchronized}
            if ex=="delta" and any(k in data for k in ("buy","sell","bids","asks")):
                typ=str(raw.get("type",raw.get("channel",data.get("action","")))).lower()
                snap=typ in ("snapshot","initial")
                if snap: b.bids.clear(); b.asks.clear()
                self.apply(b.bids,data.get("buy",data.get("bids",[]))); self.apply(b.asks,data.get("sell",data.get("asks",[])))
                if snap: b.synchronized=bool(b.bids and b.asks); b.error=None if b.synchronized else "Empty snapshot"
                self.touch(ex,b,ts); return {"type":"book_snapshot" if snap else "book_delta","synchronized":b.synchronized}
            tape=[]
            if ex=="binance" and data.get("e")=="aggTrade": tape=[data]
            elif topic.startswith("publicTrade"): tape=data if isinstance(data,list) else [data]
            elif ex=="delta" and "price" in data and ("size" in data or "quantity" in data): tape=[data]
            for t in tape:
                p=float(t.get("p",t.get("price",0))); q=float(t.get("q",t.get("v",t.get("size",t.get("quantity",0)))))
                if p<=0 or q<=0: continue
                maker=t.get("m"); side=("sell" if maker else "buy") if isinstance(maker,bool) else str(t.get("S",t.get("side",t.get("takerSide","")))).lower() or None
                if side not in ("buy","sell"): side=None
                trade=Trade(ex,symbol,p,q,side,self.as_int(t.get("T") or t.get("timestamp") or ts),int(time.time()*1000))
                key=self.key(ex,symbol); self.trades.setdefault(key,[]).append(trade)
                self.trades[key]=self.trades[key][-5000:]; self.touch(ex,b,ts)
                return {"type":"trade","exchange":ex,"symbol":symbol,"price":p,"quantity":q,"side":side}
        except (ValueError,TypeError,KeyError) as err:
            b.error="Payload parse error: "+str(err); self.errors[self.key(ex,symbol)]=b.error
            return {"type":"parse_error","error":b.error}
        return None
    def get_book(self,exchange,symbol):
        b=self.books.get(self.key(exchange,symbol))
        if b is None:return None
        age=None if b.received_ts is None else max(0,time.time()-b.received_ts/1000)
        stale=age is None or age>self.stale_after_seconds; b.stale=stale
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
        return {"phase":3,"engine":"unified_market_data","stale_after_seconds":self.stale_after_seconds,
          "exchanges":{x:{"messages_received":self.counts.get(x,0),"last_message_age_seconds":round(now-self.last_seen[x],3) if x in self.last_seen else None} for x in sorted(set(self.counts)|{b.exchange for b in self.books.values()})},
          "books":{k:{"synchronized":b.synchronized,"stale":b.stale,"integrity_error":b.error} for k,b in self.books.items()},
          "trade_streams":{k:len(v) for k,v in self.trades.items()},"errors":self.errors.copy()}
