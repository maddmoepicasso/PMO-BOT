from __future__ import annotations

import collections
import math
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


K = 8
D = 5.0
EWMA_ALPHA = 0.25
RES_W = {"target": 0.6, "corr": 0.4}
R_HIGH = 2.0
TRADE_WINDOW_MS = 200
TRADE_THRESHOLD = 3
WICK_RETRACE_PCT = 0.3
ATR_MULT_STOP = 0.6

ewma_fragility: Dict[str, float] = collections.defaultdict(lambda: 1.0)
depth_norm: Dict[str, float] = collections.defaultdict(lambda: 1000.0)
size_thresholds: Dict[str, float] = collections.defaultdict(lambda: 50.0)


def current_ts_ms() -> int:
    return int(time.time() * 1000)


def sma(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def atr(prices: List[float], window: int = 14) -> float:
    if len(prices) < 2:
        return 0.0
    ranges = []
    usable = min(len(prices) - 1, max(1, window))
    for offset in range(1, usable + 1):
        ranges.append(abs(float(prices[-offset]) - float(prices[-offset - 1])))
    return sma(ranges)


def compute_fragility(book_levels: List[Tuple[float, float, float]], depth_norm_value: float) -> float:
    if not book_levels:
        return 1.0
    fragility = 0.0
    best_price = float(book_levels[0][0])
    for price, bid_size, ask_size in book_levels[:K]:
        level_distance = abs(float(price) - best_price)
        level_size = max(0.0, float(bid_size)) + max(0.0, float(ask_size))
        weight = math.exp(-level_distance / D)
        fragility += (level_size / max(float(depth_norm_value), 1.0)) * weight
    return 1.0 / max(fragility, 1e-9)


def update_ewma(symbol: str, fragility: float) -> float:
    prev = ewma_fragility[symbol]
    value = EWMA_ALPHA * fragility + (1.0 - EWMA_ALPHA) * prev
    ewma_fragility[symbol] = value
    return value


def fragility_z(symbol: str, fragility: float) -> float:
    baseline = ewma_fragility[symbol] or fragility
    return fragility / max(baseline, 1e-9)


def aggregate_aggressor(symbol: str, trades: List[Dict[str, Any]], window_ms: int, now_ms: Optional[int] = None) -> Tuple[int, int]:
    if now_ms is None:
        timestamps = [int(t.get("ts", 0) or 0) for t in trades if t.get("ts")]
        now_ms = max(timestamps) if timestamps else current_ts_ms()
    buys = sells = 0
    for trade in trades:
        if trade.get("symbol") != symbol:
            continue
        if now_ms - int(trade.get("ts", 0) or 0) > window_ms:
            continue
        if float(trade.get("size", 0) or 0) < size_thresholds[symbol]:
            continue
        side = str(trade.get("side", "")).lower()
        if side == "buy":
            buys += 1
        elif side == "sell":
            sells += 1
    return buys, sells


def detect_wick(price_series: List[float], lookback: int = 50) -> Optional[Dict[str, float]]:
    if len(price_series) < 5:
        return None
    recent = [float(value) for value in price_series[-lookback:] if float(value) > 0]
    if len(recent) < 5:
        return None
    high = max(recent)
    low = min(recent)
    latest = recent[-1]
    if (high - low) / max(low, 1e-9) < 0.001:
        return None
    if latest <= high - (high - low) * WICK_RETRACE_PCT:
        return {
            "type": "bear_wick" if recent.index(high) > recent.index(low) else "bull_wick",
            "high": high,
            "low": low,
        }
    return None


def touch_price(book_levels: List[Tuple[float, float, float]], side: str) -> Optional[float]:
    if not book_levels:
        return None
    return float(book_levels[0][0])


def compute_size_by_liquidity(entry_price: float, book_levels: List[Tuple[float, float, float]]) -> int:
    del entry_price
    total_depth = sum(float(bid) + float(ask) for _, bid, ask in book_levels[:K]) if book_levels else 0.0
    return max(1, int(total_depth * 0.1))


def reset_state() -> None:
    ewma_fragility.clear()
    depth_norm.clear()
    size_thresholds.clear()


def cobr_on_tick(
    target_sym: str,
    corr_sym: Optional[str],
    books: Dict[str, List[Tuple[float, float, float]]],
    trades: List[Dict[str, Any]],
    price_series: Dict[str, List[float]],
    now_ms: Optional[int] = None,
) -> List[Dict[str, Any]]:
    symbols = [target_sym]
    if corr_sym and corr_sym in books:
        symbols.append(corr_sym)

    fragility_scores: Dict[str, float] = {}
    for symbol in symbols:
        fragility = compute_fragility(books.get(symbol, []), depth_norm[symbol])
        z_before_update = fragility_z(symbol, fragility)
        update_ewma(symbol, fragility)
        fragility_scores[symbol] = z_before_update

    resonance = RES_W["target"] * fragility_scores[target_sym]
    if corr_sym and corr_sym in fragility_scores:
        resonance += RES_W["corr"] * fragility_scores[corr_sym]

    total_buys = total_sells = 0
    for symbol in symbols:
        buys, sells = aggregate_aggressor(symbol, trades, TRADE_WINDOW_MS, now_ms=now_ms)
        total_buys += buys
        total_sells += sells
    flow_direction = "buy" if total_buys > total_sells else "sell"
    flow_strength = abs(total_buys - total_sells)

    signals: List[Dict[str, Any]] = []
    if resonance > R_HIGH and flow_strength >= TRADE_THRESHOLD:
        side = "long" if flow_direction == "buy" else "short"
        entry_price = touch_price(books.get(target_sym, []), side)
        if entry_price is not None:
            stop_offset = atr(price_series.get(target_sym, []), 14) * ATR_MULT_STOP
            stop = entry_price - stop_offset if side == "long" else entry_price + stop_offset
            signals.append({
                "type": "cobr_momentum",
                "side": side,
                "price": entry_price,
                "stop": stop,
                "size": compute_size_by_liquidity(entry_price, books.get(target_sym, [])),
                "resonance": round(resonance, 4),
                "flow_strength": flow_strength,
                "signal_only": True,
            })

    wick = detect_wick(price_series.get(target_sym, []))
    if resonance > R_HIGH and wick:
        side = "short" if wick["type"] == "bear_wick" else "long"
        entry_price = touch_price(books.get(target_sym, []), side)
        if entry_price is not None:
            stop_offset = atr(price_series.get(target_sym, []), 14) * ATR_MULT_STOP
            stop = entry_price - stop_offset if side == "long" else entry_price + stop_offset
            top = books.get(target_sym, [(0, 1, 1)])[0]
            signals.append({
                "type": "cobr_fade",
                "side": side,
                "price": entry_price,
                "stop": stop,
                "size": max(1, int((float(top[1]) + float(top[2])) * 0.05)),
                "resonance": round(resonance, 4),
                "wick": wick,
                "signal_only": True,
            })
    return signals


def make_synthetic_book(mid: float = 100.0) -> List[Tuple[float, float, float]]:
    levels = []
    for index in range(K):
        levels.append((
            round(mid + index * 0.01, 5),
            max(1, int(random.gauss(200, 50))),
            max(1, int(random.gauss(200, 50))),
        ))
    return levels


@dataclass
class Signal:
    ts: float
    side: Optional[str]
    price: Optional[float]
    qty: Optional[float]


class COBRSignal:
    """Compatibility wrapper for notebook demos; real PMO COBR uses cobr_on_tick."""

    def generate(self, market_tick: Dict[str, Any]) -> Signal:
        side: Optional[str] = None
        price = market_tick.get("price")
        qty = float(market_tick.get("qty", market_tick.get("size", 1.0)) or 1.0)
        if "prev_price" in market_tick and price is not None:
            current_price = float(price)
            previous_price = float(market_tick["prev_price"])
            if current_price < previous_price:
                side = "buy"
            elif current_price > previous_price:
                side = "sell"
        return Signal(ts=float(market_tick.get("ts", current_ts_ms())), side=side, price=price, qty=qty)


if __name__ == "__main__":
    reset_state()
    books = {"TGT": make_synthetic_book(100.0), "CORR": make_synthetic_book(100.02)}
    prices = {"TGT": [100.0], "CORR": [100.02]}
    trades: List[Dict[str, Any]] = []
    for step in range(200):
        now = current_ts_ms()
        if random.random() < 0.05:
            books["TGT"][0] = (books["TGT"][0][0], 10, 10)
            books["CORR"][0] = (books["CORR"][0][0], 15, 12)
            trades.append({"symbol": "TGT", "price": books["TGT"][0][0], "size": 100, "side": "buy", "ts": now})
        else:
            books["TGT"] = make_synthetic_book(100.0 + random.gauss(0, 0.02))
            books["CORR"] = make_synthetic_book(100.02 + random.gauss(0, 0.02))
        prices["TGT"].append(books["TGT"][0][0] + random.gauss(0, 0.01))
        prices["CORR"].append(books["CORR"][0][0] + random.gauss(0, 0.01))
        trades = [trade for trade in trades if now - trade["ts"] < 1000]
        emitted = cobr_on_tick("TGT", "CORR", books, trades, prices, now_ms=now)
        if emitted:
            print(f"Step {step} signals:", emitted)
        time.sleep(0.01)
