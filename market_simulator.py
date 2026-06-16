from __future__ import annotations

import collections
import heapq
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


OrderTuple = Tuple[str, float, str, int]


@dataclass
class Fill:
    ts: float
    price: float
    qty: float
    side: str
    order_id: str


@dataclass
class Order:
    order_id: str
    client_id: Optional[str]
    ts: float
    side: str
    price: float
    qty: float
    remaining: float
    status: str = "open"
    fills: List[Fill] = field(default_factory=list)


@dataclass
class Position:
    qty: float = 0.0
    avg_price: float = 0.0


class PriceLevel:
    def __init__(self, price: float):
        self.price = float(price)
        self.queue: collections.deque[OrderTuple] = collections.deque()

    @property
    def size(self) -> float:
        return sum(order[1] for order in self.queue)


class OrderBook:
    def __init__(self):
        self.bids: Dict[float, PriceLevel] = {}
        self.asks: Dict[float, PriceLevel] = {}
        self.best_bid: Optional[float] = None
        self.best_ask: Optional[float] = None

    def update_resting(
        self,
        side: str,
        price: float,
        size: float,
        owner: Optional[str] = None,
        order_id: Optional[str] = None,
        ts: Optional[int] = None,
    ) -> str:
        side = str(side or "").lower()
        if side not in {"bid", "ask"}:
            raise ValueError("side must be 'bid' or 'ask'")
        price = round(float(price), 5)
        size = max(0.0, float(size))
        levels = self.bids if side == "bid" else self.asks
        if price not in levels:
            levels[price] = PriceLevel(price)
        if order_id is None:
            order_id = f"rest-{side}-{price}-{random.randint(0, 1_000_000_000)}"
        if size > 0:
            levels[price].queue.append((order_id, size, owner or "rest", ts or int(time.time() * 1000)))
        self._refresh_best()
        return order_id

    def replace_level(self, side: str, price: float, size: float, owner: str = "feed", ts: Optional[int] = None) -> None:
        side = str(side or "").lower()
        price = round(float(price), 5)
        levels = self.bids if side == "bid" else self.asks
        if size <= 0:
            levels.pop(price, None)
        else:
            level = PriceLevel(price)
            level.queue.append((f"{owner}-{side}-{price}-{ts or int(time.time() * 1000)}", float(size), owner, ts or 0))
            levels[price] = level
        self._refresh_best()

    def _refresh_best(self) -> None:
        self.best_bid = max(self.bids.keys()) if self.bids else None
        self.best_ask = min(self.asks.keys()) if self.asks else None

    def get_topk(self, k: int = 8) -> List[Tuple[float, float, float]]:
        bids_sorted = sorted(self.bids.items(), key=lambda item: -item[0])[:k]
        asks_sorted = sorted(self.asks.items(), key=lambda item: item[0])[:k]
        rows: List[Tuple[float, float, float]] = []
        for index in range(max(len(bids_sorted), len(asks_sorted))):
            bid_price = bids_sorted[index][0] if index < len(bids_sorted) else None
            bid_size = bids_sorted[index][1].size if index < len(bids_sorted) else 0.0
            ask_price = asks_sorted[index][0] if index < len(asks_sorted) else None
            ask_size = asks_sorted[index][1].size if index < len(asks_sorted) else 0.0
            price = ask_price if ask_price is not None else bid_price if bid_price is not None else 0.0
            rows.append((float(price), float(bid_size), float(ask_size)))
        return rows

    def match_ioc(self, side: str, size: float) -> Tuple[List[Tuple[float, float]], float]:
        side = str(side or "").lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        remaining = max(0.0, float(size))
        requested = remaining
        fills: List[Tuple[float, float]] = []
        opposite = self.asks if side == "buy" else self.bids

        while remaining > 0 and opposite:
            best = min(opposite.keys()) if side == "buy" else max(opposite.keys())
            level = opposite[best]
            while remaining > 0 and level.queue:
                order_id, level_remaining, owner, ts = level.queue[0]
                take = min(level_remaining, remaining)
                remaining -= take
                level_remaining -= take
                fills.append((best, take))
                if level_remaining <= 0:
                    level.queue.popleft()
                else:
                    level.queue[0] = (order_id, level_remaining, owner, ts)
            if not level.queue:
                del opposite[best]

        self._refresh_best()
        return fills, requested - remaining


class MarketSimulator:
    def __init__(
        self,
        decision_latency_ms: int = 5,
        exchange_latency_ms: int = 5,
        symbol: str = "TGT",
        starting_cash: float = 100000.0,
    ):
        self.book = OrderBook()
        self.time = 0
        self.events: List[Tuple[int, int, Callable[..., Any], tuple, dict]] = []
        self.decision_latency_ms = int(max(0, decision_latency_ms))
        self.exchange_latency_ms = int(max(0, exchange_latency_ms))
        self.symbol = symbol
        self._counter = 0
        self.logs: List[Dict[str, Any]] = []
        self.trades: List[Dict[str, Any]] = []
        self.price_series: List[float] = []
        self.orders: Dict[str, Order] = {}
        self.fills: List[Fill] = []
        self.cash = float(starting_cash)
        self.position = Position()
        self.next_ts = 0.0

    def schedule(self, ts_ms: int, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self._counter += 1
        heapq.heappush(self.events, (int(ts_ms), self._counter, fn, args, kwargs))

    def run_until_empty(self) -> None:
        while self.events:
            ts_ms, _, fn, args, kwargs = heapq.heappop(self.events)
            self.time = int(ts_ms)
            fn(*args, **kwargs)

    def seed_resting(self, side: str, price: float, size: float) -> None:
        self.book.update_resting(side, price, size, ts=self.time)
        self.price_series.append(float(price))

    def ingest_trade(self, trade: Dict[str, Any]) -> None:
        normalized = {
            "ts": float(trade.get("ts", self._next_ts())),
            "price": float(trade.get("price", 0)),
            "qty": float(trade.get("qty", trade.get("size", 0))),
            "size": float(trade.get("size", trade.get("qty", 0))),
            "side": str(trade.get("side", "")).lower() or "buy",
            "symbol": trade.get("symbol") or self.symbol,
        }
        self.trades.append(normalized)
        self.trades.sort(key=lambda item: float(item.get("ts", 0)))
        if normalized["price"] > 0:
            self.price_series.append(normalized["price"])

    def place_limit(
        self,
        side: str,
        price: float,
        qty: float,
        ts: Optional[float] = None,
        client_id: Optional[str] = None,
    ) -> str:
        if ts is None:
            ts = self._next_ts()
        order_id = str(uuid.uuid4())
        order = Order(
            order_id=order_id,
            client_id=client_id,
            ts=float(ts),
            side=str(side or "").lower(),
            price=float(price),
            qty=float(qty),
            remaining=float(qty),
        )
        if order.side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        self.orders[order_id] = order
        self._attempt_match(order)
        return order_id

    def cancel_order(self, order_id: str, ts: Optional[float] = None) -> bool:
        del ts
        order = self.orders.get(order_id)
        if not order or order.status in {"filled", "cancelled"}:
            return False
        order.status = "filled" if order.remaining <= 0 else "cancelled"
        return True

    def list_orders(self) -> List[Order]:
        return list(self.orders.values())

    def list_fills(self) -> List[Fill]:
        return list(self.fills)

    def get_pnl(self, mark_price: Optional[float] = None) -> Dict[str, float]:
        if mark_price is None:
            mark_price = self.fills[-1].price if self.fills else (self.price_series[-1] if self.price_series else None)
        unrealized = 0.0
        if mark_price is not None:
            unrealized = (float(mark_price) - self.position.avg_price) * self.position.qty
        realized = sum(float(getattr(fill, "realized_pnl", 0.0)) for fill in self.fills)
        equity_mark = float(mark_price) if mark_price is not None else 0.0
        return {
            "cash": round(self.cash, 4),
            "position_qty": round(self.position.qty, 6),
            "position_avg_price": round(self.position.avg_price, 6),
            "mark_price": equity_mark,
            "unrealized_pnl": round(unrealized, 4),
            "realized_pnl": round(realized, 4),
            "total_equity": round(self.cash + self.position.qty * equity_mark, 4),
        }

    def _next_ts(self) -> float:
        self.next_ts += 0.001
        return self.next_ts

    def _trade_qty(self, trade: Dict[str, Any]) -> float:
        return float(trade.get("qty", trade.get("size", 0)) or 0)

    def _set_trade_qty(self, trade: Dict[str, Any], qty: float) -> None:
        trade["qty"] = max(0.0, float(qty))
        trade["size"] = trade["qty"]

    def _attempt_match(self, order: Order) -> None:
        for trade in list(self.trades):
            if order.remaining <= 0:
                break
            trade_qty = self._trade_qty(trade)
            if trade_qty <= 0:
                if trade in self.trades:
                    self.trades.remove(trade)
                continue
            trade_price = float(trade.get("price", 0))
            buy_fill = order.side == "buy" and trade_price <= order.price
            sell_fill = order.side == "sell" and trade_price >= order.price
            if not (buy_fill or sell_fill):
                continue
            fill_qty = min(order.remaining, trade_qty)
            self._apply_fill(order, trade, fill_qty)
            self._set_trade_qty(trade, trade_qty - fill_qty)
            if self._trade_qty(trade) <= 0 and trade in self.trades:
                self.trades.remove(trade)

        if order.remaining <= 0:
            order.status = "filled"
        elif order.fills:
            order.status = "partially_filled"
        else:
            order.status = "open"

    def _apply_fill(self, order: Order, trade: Dict[str, Any], qty: float) -> None:
        fill = Fill(
            ts=float(trade.get("ts", order.ts)),
            price=float(trade.get("price", order.price)),
            qty=float(qty),
            side=order.side,
            order_id=order.order_id,
        )
        order.fills.append(fill)
        self.fills.append(fill)
        order.remaining -= float(qty)
        self._update_position_and_cash(fill)
        self.logs.append({
            "time": fill.ts,
            "type": "limit_fill",
            "order_id": fill.order_id,
            "price": fill.price,
            "qty": fill.qty,
            "side": fill.side,
            "live_order_allowed": False,
        })

    def _update_position_and_cash(self, fill: Fill) -> None:
        if fill.side == "buy":
            previous_qty = self.position.qty
            previous_avg = self.position.avg_price
            new_qty = previous_qty + fill.qty
            if previous_qty < 0:
                covered = min(fill.qty, abs(previous_qty))
                realized_pnl = covered * (previous_avg - fill.price)
                setattr(fill, "realized_pnl", realized_pnl)
            if new_qty > 0:
                opening_qty = fill.qty if previous_qty >= 0 else max(0.0, new_qty)
                retained_value = max(previous_qty, 0.0) * previous_avg
                self.position.avg_price = (retained_value + opening_qty * fill.price) / max(new_qty, 1e-9)
            elif new_qty == 0:
                self.position.avg_price = 0.0
            else:
                self.position.avg_price = previous_avg
            self.position.qty = new_qty
            self.cash -= fill.qty * fill.price
        else:
            previous_qty = self.position.qty
            previous_avg = self.position.avg_price
            new_qty = previous_qty - fill.qty
            if previous_qty > 0:
                sold = min(fill.qty, previous_qty)
                realized_pnl = sold * (fill.price - previous_avg)
                setattr(fill, "realized_pnl", realized_pnl)
            if new_qty < 0:
                opening_qty = fill.qty if previous_qty <= 0 else max(0.0, abs(new_qty))
                retained_value = abs(min(previous_qty, 0.0)) * previous_avg
                self.position.avg_price = (retained_value + opening_qty * fill.price) / max(abs(new_qty), 1e-9)
            elif new_qty == 0:
                self.position.avg_price = 0.0
            else:
                self.position.avg_price = previous_avg
            self.position.qty = new_qty
            self.cash += fill.qty * fill.price

    def submit_ioc(self, submit_ts: int, side: str, size: float, client_id: Optional[str] = None) -> None:
        arrival = int(submit_ts) + self.exchange_latency_ms
        self.schedule(arrival, self._process_ioc, side, size, client_id)

    def _process_ioc(self, side: str, size: float, client_id: Optional[str]) -> Tuple[List[Tuple[float, float]], float]:
        fills, filled_qty = self.book.match_ioc(side, size)
        for price, qty in fills:
            trade = {"symbol": self.symbol, "price": price, "size": qty, "side": side, "ts": self.time}
            self.trades.append(trade)
            self.price_series.append(price)
            self.trades = [item for item in self.trades if self.time - int(item.get("ts", 0)) <= 1000]
            self.logs.append({
                "time": self.time,
                "type": "simulated_fill",
                "price": price,
                "size": qty,
                "side": side,
                "client": client_id or "SIM",
                "live_order_allowed": False,
            })
        return fills, filled_qty


def synthetic_feed(duration_ms: int = 2000, step_ms: int = 20, symbol: str = "TGT") -> List[Dict[str, Any]]:
    feed: List[Dict[str, Any]] = []
    ts = 0
    mid = 100.0
    seed_levels: List[Dict[str, Any]] = []
    for index in range(5):
        seed_levels.append({"side": "bid", "price": round(mid - index * 0.01, 5), "size": 200})
        seed_levels.append({"side": "ask", "price": round(mid + index * 0.01, 5), "size": 200})
    feed.append({"ts": 0, "type": "seed", "symbol": symbol, "data": seed_levels})

    while ts < duration_ms:
        ts += step_ms
        price = mid + random.gauss(0, 0.02)
        pulse_period = max(step_ms * 10, 200)
        forced_pulse = ts % pulse_period == 0
        if forced_pulse or random.random() < 0.12:
            thin_price = round(price, 5)
            thin_levels: List[Dict[str, Any]] = []
            for index in range(8):
                thin_levels.append({"side": "bid", "price": round(thin_price - index * 0.01, 5), "size": 1})
                thin_levels.append({"side": "ask", "price": round(thin_price + index * 0.01, 5), "size": 1})
            feed.append({
                "ts": ts,
                "type": "book",
                "symbol": symbol,
                "replace_book": True,
                "data": thin_levels,
            })
            side = "buy" if random.random() >= 0.35 else "sell"
            feed.append({"ts": ts + 1, "type": "trade", "symbol": symbol, "data": {"price": thin_price, "size": 125, "side": side}})
            feed.append({"ts": ts + 2, "type": "trade", "symbol": symbol, "data": {"price": thin_price, "size": 125, "side": side}})
            feed.append({"ts": ts + 3, "type": "trade", "symbol": symbol, "data": {"price": thin_price, "size": 125, "side": side}})
        else:
            feed.append({
                "ts": ts,
                "type": "book",
                "symbol": symbol,
                "data": [
                    {"side": "bid", "price": round(price - 0.001, 5), "size": 200},
                    {"side": "ask", "price": round(price + 0.001, 5), "size": 200},
                ],
            })
    return feed


def run_replay(sim: MarketSimulator, feed_events: List[Dict[str, Any]], cobr_module: Any) -> List[Dict[str, Any]]:
    def apply_event(event: Dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "seed":
            for level in event.get("data", []):
                sim.seed_resting(level["side"], level["price"], level["size"])
        elif event_type == "book":
            if event.get("replace_book"):
                sim.book.bids.clear()
                sim.book.asks.clear()
                sim.book._refresh_best()
            for level in event.get("data", []):
                sim.book.replace_level(level["side"], level["price"], level["size"], ts=sim.time)
                sim.price_series.append(float(level["price"]))
        elif event_type == "trade":
            data = event.get("data", {})
            trade = {
                "symbol": event.get("symbol") or sim.symbol,
                "price": float(data.get("price", 0)),
                "size": float(data.get("size", 0)),
                "side": str(data.get("side", "")).lower(),
                "ts": int(event.get("ts", sim.time)),
            }
            sim.trades.append(trade)
            sim.price_series.append(trade["price"])
            sim.trades = [item for item in sim.trades if sim.time - int(item.get("ts", 0)) <= 1000]

        decision_ts = int(event.get("ts", sim.time)) + sim.decision_latency_ms

        def decision_call() -> None:
            topk_target = sim.book.get_topk(k=8)
            if not topk_target:
                return
            books = {sim.symbol: topk_target, "CORR": topk_target}
            price_series = {sim.symbol: list(sim.price_series[-80:]), "CORR": list(sim.price_series[-80:])}
            signals = cobr_module.cobr_on_tick(sim.symbol, "CORR", books, list(sim.trades), price_series, now_ms=sim.time)
            for signal in signals:
                signal["live_order_allowed"] = False
                signal["simulation_only"] = True
                side = "buy" if signal.get("side") == "long" else "sell"
                sim.submit_ioc(decision_ts, side, float(signal.get("size", 1)), client_id="COBR_SIM")
                sim.logs.append({"time": sim.time, "type": "signal", "signal": signal, "live_order_allowed": False})

        sim.schedule(decision_ts, decision_call)

    for event in feed_events:
        sim.schedule(int(event.get("ts", 0)), apply_event, event)
    sim.run_until_empty()
    return sim.logs


def run_synthetic_cobr_replay(duration_ms: int = 2000, step_ms: int = 20) -> Dict[str, Any]:
    import cobr_signal

    if hasattr(cobr_signal, "reset_state"):
        cobr_signal.reset_state()
    sim = MarketSimulator(decision_latency_ms=5, exchange_latency_ms=5)
    logs = run_replay(sim, synthetic_feed(duration_ms=duration_ms, step_ms=step_ms), cobr_signal)
    signals = [row for row in logs if row.get("type") == "signal"]
    fills = [row for row in logs if row.get("type") == "simulated_fill"]
    return {
        "ok": True,
        "engine": "COBR Market Simulator",
        "mode": "RESEARCH_ONLY_SIMULATION",
        "live_order_allowed": False,
        "duration_ms": duration_ms,
        "step_ms": step_ms,
        "signals": len(signals),
        "fills": len(fills),
        "logs": logs[-100:],
    }


if __name__ == "__main__":
    result = run_synthetic_cobr_replay(duration_ms=2000, step_ms=20)
    print(f"Signals emitted: {result['signals']}, simulated fills: {result['fills']}")
    for row in result["logs"][:10]:
        print(row)
