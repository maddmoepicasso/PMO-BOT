"""
PMO intraday edge engine bundle.

Five read-only edge checks:
- ORB: opening range breakout
- RS: relative strength versus SPY
- POC: volume profile point of control
- GAP: gap context versus previous close
- SEC: sector momentum confirmation

The module returns serializable metadata. It does not place orders, unlock
live trading, or change PMO settings.
"""

from __future__ import annotations

import datetime as _datetime
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("pmo.edge_engines")

MODIFIERS = {
    "orb_aligned": 5,
    "orb_against": -4,
    "orb_inside": 0,
    "rs_strong": 5,
    "rs_neutral": 0,
    "rs_weak": -4,
    "poc_clear": 3,
    "poc_magnet": -3,
    "poc_at_entry": 2,
    "gap_up_hold": 4,
    "gap_up_fill": -3,
    "gap_down_hold": -3,
    "gap_down_fill": 2,
    "gap_flat": 0,
    "sector_aligned": 4,
    "sector_neutral": 0,
    "sector_against": -4,
}

COMBINED_CAP = 15

SECTOR_MAP = {
    "NVDA": "$SOX", "AMD": "$SOX", "INTC": "$SOX", "QCOM": "$SOX", "MU": "$SOX",
    "AMAT": "$SOX", "LRCX": "$SOX", "KLAC": "$SOX", "AVGO": "$SOX", "TSM": "$SOX",
    "AAPL": "$IUXX", "MSFT": "$IUXX", "GOOGL": "$IUXX", "META": "$IUXX", "AMZN": "$IUXX",
    "NFLX": "$IUXX", "TSLA": "$IUXX", "CRM": "$IUXX", "ADBE": "$IUXX",
    "GLD": "$XAU", "GDX": "$XAU", "NEM": "$XAU", "GOLD": "$XAU", "AEM": "$XAU",
    "CVX": "$OSX", "XOM": "$OSX", "OXY": "$OSX", "SLB": "$OSX", "HAL": "$OSX",
    "XLU": "$UTY", "NEE": "$UTY", "DUK": "$UTY", "SO": "$UTY",
    "DHI": "$HGX", "LEN": "$HGX", "PHM": "$HGX", "TOL": "$HGX",
    "SPY": "$DOWC", "DIA": "$DOWC", "IWM": "$DOWC", "QQQ": "$IUXX",
    "JPM": "$DOWC", "BAC": "$DOWC", "GS": "$DOWC", "MS": "$DOWC",
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _direction(value: Any) -> str:
    text = str(value or "long").strip().lower()
    if text in {"short", "sell", "put", "put_bias", "bearish"}:
        return "short"
    return "long"


def _bar_time(value: Any) -> Optional[_datetime.time]:
    if value is None:
        return None
    if isinstance(value, _datetime.datetime):
        return value.time()
    text = str(value).strip()
    if not text:
        return None
    try:
        return _datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).time()
    except Exception:
        return None


@dataclass
class ORBResult:
    signal: str = "NONE"
    orb_high: Any = ""
    orb_low: Any = ""
    orb_width_pct: float = 0.0
    current_price: Any = ""
    breakout_pct: float = 0.0
    score_modifier: int = 0
    note: str = ""


@dataclass
class RSResult:
    signal: str = "NONE"
    ticker_chg_pct: float = 0.0
    spy_chg_pct: float = 0.0
    rs_delta: float = 0.0
    score_modifier: int = 0
    note: str = ""


@dataclass
class POCResult:
    signal: str = "NONE"
    poc_price: Any = ""
    current_price: Any = ""
    target_price: Any = ""
    poc_dist_pct: float = 0.0
    in_path: bool = False
    score_modifier: int = 0
    note: str = ""


@dataclass
class GAPResult:
    signal: str = "NONE"
    gap_pct: float = 0.0
    gap_direction: str = "FLAT"
    gap_holding: bool = False
    current_price: Any = ""
    prev_close: Any = ""
    premarket_open: Any = ""
    score_modifier: int = 0
    note: str = ""


@dataclass
class SECResult:
    signal: str = "NONE"
    ticker: str = ""
    sector_index: str = "UNKNOWN"
    sector_chg_pct: float = 0.0
    score_modifier: int = 0
    note: str = ""


def compute_orb(bars: Iterable[Dict[str, Any]], orb_minutes: int = 15, trade_direction: str = "long") -> ORBResult:
    rows = [row for row in bars or [] if isinstance(row, dict)]
    if not rows:
        return ORBResult(note="no bars")
    orb_bars: List[Dict[str, Any]] = []
    end_minute = 30 + max(5, int(orb_minutes))
    end_hour = 9 + (end_minute // 60)
    end_minute = end_minute % 60
    for row in rows:
        row_time = _bar_time(row.get("datetime") or row.get("time") or row.get("timestamp"))
        if row_time and _datetime.time(9, 30) <= row_time <= _datetime.time(end_hour, end_minute):
            orb_bars.append(row)
    if not orb_bars:
        orb_bars = rows[: max(1, int(max(5, orb_minutes) / 5))]
    highs = [_to_float(row.get("high") or row.get("h"), 0) for row in orb_bars]
    lows = [_to_float(row.get("low") or row.get("l"), 0) for row in orb_bars]
    orb_high = max(highs or [0])
    orb_low = min(lows or [0])
    current_price = _to_float(rows[-1].get("close") or rows[-1].get("c"), 0)
    if orb_high <= 0 or orb_low <= 0 or current_price <= 0:
        return ORBResult(note="invalid ORB prices")
    width_pct = (orb_high - orb_low) / orb_low * 100.0
    direction = _direction(trade_direction)
    if current_price > orb_high:
        breakout_pct = (current_price - orb_high) / orb_high * 100.0
        return ORBResult("BULLISH", round(orb_high, 4), round(orb_low, 4), round(width_pct, 2), round(current_price, 4), round(breakout_pct, 2), MODIFIERS["orb_aligned"] if direction == "long" else MODIFIERS["orb_against"], f"above ORB by {breakout_pct:.2f}%")
    if current_price < orb_low:
        breakout_pct = (orb_low - current_price) / orb_low * 100.0
        return ORBResult("BEARISH", round(orb_high, 4), round(orb_low, 4), round(width_pct, 2), round(current_price, 4), round(breakout_pct, 2), MODIFIERS["orb_aligned"] if direction == "short" else MODIFIERS["orb_against"], f"below ORB by {breakout_pct:.2f}%")
    return ORBResult("INSIDE", round(orb_high, 4), round(orb_low, 4), round(width_pct, 2), round(current_price, 4), 0.0, MODIFIERS["orb_inside"], "price inside opening range")


def compute_rs(ticker_bars: Iterable[Dict[str, Any]], spy_bars: Iterable[Dict[str, Any]], trade_direction: str = "long", rs_threshold_pct: float = 0.5) -> RSResult:
    ticker_rows = [row for row in ticker_bars or [] if isinstance(row, dict)]
    spy_rows = [row for row in spy_bars or [] if isinstance(row, dict)]
    if not ticker_rows or not spy_rows:
        return RSResult(note="missing bars")

    def pct_change(rows: List[Dict[str, Any]]) -> float:
        start = _to_float(rows[0].get("open") or rows[0].get("close"), 0)
        end = _to_float(rows[-1].get("close"), 0)
        return (end - start) / start * 100.0 if start > 0 else 0.0

    ticker_chg = pct_change(ticker_rows)
    spy_chg = pct_change(spy_rows)
    delta = ticker_chg - spy_chg
    threshold = max(0.0, _to_float(rs_threshold_pct, 0.5))
    direction = _direction(trade_direction)
    if delta >= threshold:
        mod = MODIFIERS["rs_strong"] if direction == "long" else MODIFIERS["rs_weak"]
        return RSResult("STRONG", round(ticker_chg, 3), round(spy_chg, 3), round(delta, 3), mod, f"outperforming SPY by {delta:+.2f}%")
    if delta <= -threshold:
        mod = MODIFIERS["rs_weak"] if direction == "long" else MODIFIERS["rs_strong"]
        return RSResult("WEAK", round(ticker_chg, 3), round(spy_chg, 3), round(delta, 3), mod, f"underperforming SPY by {delta:+.2f}%")
    return RSResult("NEUTRAL", round(ticker_chg, 3), round(spy_chg, 3), round(delta, 3), MODIFIERS["rs_neutral"], f"in line with SPY ({delta:+.2f}%)")


def compute_poc(bars: Iterable[Dict[str, Any]], trade_direction: str = "long", target_pct: float = 6.0, n_buckets: int = 20) -> POCResult:
    rows = [row for row in bars or [] if isinstance(row, dict)]
    if len(rows) < 5:
        return POCResult(note="too few bars")
    prices = [_to_float(row.get("close"), 0) for row in rows if _to_float(row.get("close"), 0) > 0]
    if not prices:
        return POCResult(note="no price data")
    min_price = min(prices)
    max_price = max(prices)
    if max_price <= min_price:
        return POCResult(note="flat price range")
    buckets = max(5, int(_to_float(n_buckets, 20)))
    bucket_size = (max_price - min_price) / buckets
    profile = [0.0] * buckets
    for row in rows:
        price = _to_float(row.get("close"), 0)
        volume = _to_float(row.get("volume"), 0)
        if price <= 0 or volume <= 0:
            continue
        index = min(buckets - 1, int((price - min_price) / bucket_size))
        profile[index] += volume
    poc_bucket = profile.index(max(profile))
    poc_price = min_price + (poc_bucket + 0.5) * bucket_size
    current_price = prices[-1]
    direction = _direction(trade_direction)
    target_price = current_price * (1 + target_pct / 100.0) if direction == "long" else current_price * (1 - target_pct / 100.0)
    poc_dist_pct = (poc_price - current_price) / current_price * 100.0 if current_price else 0.0
    in_path = current_price < poc_price < target_price if direction == "long" else target_price < poc_price < current_price
    at_poc = abs(poc_dist_pct) <= 0.3
    if at_poc:
        return POCResult("AT_POC", round(poc_price, 4), round(current_price, 4), round(target_price, 4), round(poc_dist_pct, 2), False, MODIFIERS["poc_at_entry"], "price at POC")
    if in_path:
        return POCResult("MAGNET", round(poc_price, 4), round(current_price, 4), round(target_price, 4), round(poc_dist_pct, 2), True, MODIFIERS["poc_magnet"], "POC between entry and target")
    return POCResult("CLEAR", round(poc_price, 4), round(current_price, 4), round(target_price, 4), round(poc_dist_pct, 2), False, MODIFIERS["poc_clear"], "POC not blocking path")


def compute_gap(bars: Iterable[Dict[str, Any]], prev_close: float, premarket_open: Optional[float] = None, trade_direction: str = "long", gap_threshold_pct: float = 0.5) -> GAPResult:
    rows = [row for row in bars or [] if isinstance(row, dict)]
    previous = _to_float(prev_close, 0)
    if not rows or previous <= 0:
        return GAPResult(note="missing data")
    market_open = _to_float(rows[0].get("open") or rows[0].get("close"), 0)
    current_price = _to_float(rows[-1].get("close"), 0)
    if market_open <= 0 or current_price <= 0:
        return GAPResult(note="invalid open/current price")
    gap_pct = (market_open - previous) / previous * 100.0
    threshold = max(0.0, _to_float(gap_threshold_pct, 0.5))
    direction = _direction(trade_direction)
    if gap_pct >= threshold:
        holding = current_price > previous
        if holding:
            mod = MODIFIERS["gap_up_hold"] if direction == "long" else MODIFIERS["gap_down_hold"]
            return GAPResult("GAP_UP_HOLD", round(gap_pct, 3), "UP", True, round(current_price, 4), round(previous, 4), round(_to_float(premarket_open, 0), 4) if premarket_open else "", mod, "gap up holding")
        mod = MODIFIERS["gap_up_fill"] if direction == "long" else MODIFIERS["gap_down_fill"]
        return GAPResult("GAP_UP_FILL", round(gap_pct, 3), "UP", False, round(current_price, 4), round(previous, 4), round(_to_float(premarket_open, 0), 4) if premarket_open else "", mod, "gap up filling")
    if gap_pct <= -threshold:
        holding = current_price < previous
        if holding:
            mod = MODIFIERS["gap_down_hold"] if direction == "long" else MODIFIERS["gap_up_hold"]
            return GAPResult("GAP_DOWN_HOLD", round(gap_pct, 3), "DOWN", True, round(current_price, 4), round(previous, 4), round(_to_float(premarket_open, 0), 4) if premarket_open else "", mod, "gap down holding")
        mod = MODIFIERS["gap_down_fill"] if direction == "long" else MODIFIERS["gap_up_fill"]
        return GAPResult("GAP_DOWN_FILL", round(gap_pct, 3), "DOWN", False, round(current_price, 4), round(previous, 4), round(_to_float(premarket_open, 0), 4) if premarket_open else "", mod, "gap down filling")
    return GAPResult("FLAT", round(gap_pct, 3), "FLAT", False, round(current_price, 4), round(previous, 4), round(_to_float(premarket_open, 0), 4) if premarket_open else "", MODIFIERS["gap_flat"], "no significant gap")


def compute_sector(ticker: str, sector_change_pct: float, trade_direction: str = "long", sector_index: Optional[str] = None, sector_threshold_pct: float = 0.3) -> SECResult:
    clean = str(ticker or "").strip().upper()
    index = sector_index or SECTOR_MAP.get(clean, "UNKNOWN")
    if index == "UNKNOWN":
        return SECResult("NONE", clean, "UNKNOWN", 0.0, 0, f"no sector mapping for {clean}")
    change = _to_float(sector_change_pct, 0)
    threshold = max(0.0, _to_float(sector_threshold_pct, 0.3))
    direction = _direction(trade_direction)
    if change >= threshold:
        sector_direction = "BULLISH"
    elif change <= -threshold:
        sector_direction = "BEARISH"
    else:
        sector_direction = "NEUTRAL"
    if sector_direction == "BULLISH" and direction == "long":
        return SECResult("ALIGNED", clean, index, round(change, 3), MODIFIERS["sector_aligned"], f"{index} up {change:+.2f}%")
    if sector_direction == "BEARISH" and direction == "short":
        return SECResult("ALIGNED", clean, index, round(change, 3), MODIFIERS["sector_aligned"], f"{index} down {change:+.2f}%")
    if sector_direction == "NEUTRAL":
        return SECResult("NEUTRAL", clean, index, round(change, 3), MODIFIERS["sector_neutral"], f"{index} flat {change:+.2f}%")
    return SECResult("AGAINST", clean, index, round(change, 3), MODIFIERS["sector_against"], f"{index} {change:+.2f}% against trade")


@dataclass
class EdgeResult:
    orb: ORBResult = field(default_factory=ORBResult)
    rs: RSResult = field(default_factory=RSResult)
    poc: POCResult = field(default_factory=POCResult)
    gap: GAPResult = field(default_factory=GAPResult)
    sec: SECResult = field(default_factory=SECResult)
    combined_score_modifier: int = 0
    edge_signal: str = "NEUTRAL"
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0

    def get_journal_dict(self) -> Dict[str, Any]:
        return {
            "orb_signal": self.orb.signal,
            "orb_mod": self.orb.score_modifier,
            "orb_high": self.orb.orb_high,
            "orb_low": self.orb.orb_low,
            "rs_signal": self.rs.signal,
            "rs_mod": self.rs.score_modifier,
            "rs_delta_pct": self.rs.rs_delta,
            "poc_signal": self.poc.signal,
            "poc_mod": self.poc.score_modifier,
            "poc_price": self.poc.poc_price,
            "gap_signal": self.gap.signal,
            "gap_mod": self.gap.score_modifier,
            "gap_pct": self.gap.gap_pct,
            "sec_signal": self.sec.signal,
            "sec_mod": self.sec.score_modifier,
            "sec_index": self.sec.sector_index,
            "edge_combined_mod": self.combined_score_modifier,
            "edge_signal": self.edge_signal,
            "edge_bull_count": self.bullish_count,
            "edge_bear_count": self.bearish_count,
        }

    def get_dashboard_dict(self) -> Dict[str, Any]:
        return {
            "orb": {"signal": self.orb.signal, "mod": self.orb.score_modifier, "note": self.orb.note},
            "rs": {"signal": self.rs.signal, "mod": self.rs.score_modifier, "note": self.rs.note},
            "poc": {"signal": self.poc.signal, "mod": self.poc.score_modifier, "note": self.poc.note},
            "gap": {"signal": self.gap.signal, "mod": self.gap.score_modifier, "note": self.gap.note},
            "sector": {"signal": self.sec.signal, "mod": self.sec.score_modifier, "note": self.sec.note, "index": self.sec.sector_index},
            "combined": {
                "mod": self.combined_score_modifier,
                "signal": self.edge_signal,
                "bulls": self.bullish_count,
                "bears": self.bearish_count,
                "neutrals": self.neutral_count,
            },
        }


class EdgeEngineBundle:
    """Runs the five PMO intraday edge engines together."""

    def analyze(
        self,
        ticker: str,
        bars: Iterable[Dict[str, Any]],
        spy_bars: Optional[Iterable[Dict[str, Any]]] = None,
        sector_index: Optional[str] = None,
        sector_change_pct: float = 0.0,
        prev_close: float = 0.0,
        premarket_open: Optional[float] = None,
        trade_direction: str = "long",
        orb_minutes: int = 15,
        target_pct: float = 6.0,
        rs_threshold_pct: float = 0.5,
        poc_buckets: int = 20,
        gap_threshold_pct: float = 0.5,
        sector_threshold_pct: float = 0.3,
        combined_cap: int = COMBINED_CAP,
    ) -> EdgeResult:
        direction = _direction(trade_direction)
        rows = [row for row in bars or [] if isinstance(row, dict)]
        spy_rows = [row for row in spy_bars or [] if isinstance(row, dict)]
        orb = compute_orb(rows, orb_minutes, direction)
        rs = compute_rs(rows, spy_rows, direction, rs_threshold_pct) if spy_rows else RSResult(note="no SPY bars")
        poc = compute_poc(rows, direction, target_pct, poc_buckets)
        gap = compute_gap(rows, prev_close, premarket_open, direction, gap_threshold_pct) if prev_close else GAPResult(note="no previous close")
        sec = compute_sector(ticker, sector_change_pct, direction, sector_index, sector_threshold_pct)
        raw = orb.score_modifier + rs.score_modifier + poc.score_modifier + gap.score_modifier + sec.score_modifier
        cap = max(0, int(_to_float(combined_cap, COMBINED_CAP)))
        combined = max(-cap, min(cap, raw)) if cap else raw
        signals = [orb.score_modifier, rs.score_modifier, poc.score_modifier, gap.score_modifier, sec.score_modifier]
        bulls = sum(1 for item in signals if item > 0)
        bears = sum(1 for item in signals if item < 0)
        neutrals = sum(1 for item in signals if item == 0)
        if combined >= 8:
            edge_signal = "STRONG_BULLISH"
        elif combined >= 4:
            edge_signal = "BULLISH"
        elif combined <= -8:
            edge_signal = "STRONG_BEARISH"
        elif combined <= -4:
            edge_signal = "BEARISH"
        else:
            edge_signal = "NEUTRAL"
        return EdgeResult(orb, rs, poc, gap, sec, int(combined), edge_signal, bulls, bears, neutrals)


EDGE_JOURNAL_COLUMNS = [
    "orb_signal", "orb_mod", "orb_high", "orb_low",
    "rs_signal", "rs_mod", "rs_delta_pct",
    "poc_signal", "poc_mod", "poc_price",
    "gap_signal", "gap_mod", "gap_pct",
    "sec_signal", "sec_mod", "sec_index",
    "edge_combined_mod", "edge_signal", "edge_bull_count", "edge_bear_count",
]


def _make_bars(count: int = 40, start: float = 100.0, trend: float = 0.05, seed: int = 42) -> List[Dict[str, Any]]:
    random.seed(seed)
    rows: List[Dict[str, Any]] = []
    price = start
    ts = _datetime.datetime(2026, 6, 16, 9, 30)
    for _ in range(count):
        open_price = price
        close_price = price + trend + random.gauss(0, 0.2)
        rows.append({
            "datetime": ts.isoformat(),
            "open": round(open_price, 2),
            "high": round(max(open_price, close_price) + random.uniform(0, 0.15), 2),
            "low": round(min(open_price, close_price) - random.uniform(0, 0.15), 2),
            "close": round(close_price, 2),
            "volume": random.randint(50000, 200000),
        })
        price = close_price
        ts += _datetime.timedelta(minutes=5)
    return rows


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    bundle = EdgeEngineBundle()
    result = bundle.analyze(
        ticker="NVDA",
        bars=_make_bars(40, 208.0, 0.08),
        spy_bars=_make_bars(40, 520.0, 0.03, seed=7),
        sector_change_pct=1.52,
        prev_close=207.5,
        trade_direction="long",
    )
    print("PMO Edge Engines smoke test")
    print(result.get_journal_dict())
    print(result.get_dashboard_dict())
