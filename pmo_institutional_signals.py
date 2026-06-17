"""
PMO institutional signal layer.

Research-grade market structure checks from data PMO can already receive:
- liquidity vacuum zones
- VWAP/ATR auction probes
- 3:30 PM rebalance risk
- earnings-call hedge language
- consecutive ask-side prints
- post-earnings announcement drift
- volatility risk premium context

This module is signal-only. It never places orders or mutates settings.
"""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any, Dict, Iterable, List, Optional


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "N/A"):
            return default
        text = str(value).strip().replace(",", "")
        if text.endswith("%"):
            text = text[:-1]
        return float(text)
    except Exception:
        return default


def _symbol(row: Dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").upper().strip()


def _side(value: Any) -> str:
    text = str(value or "").upper().strip()
    if text in {"CALL_BIAS", "BULLISH", "LONG", "BUY", "BULL"}:
        return "LONG"
    if text in {"PUT_BIAS", "BEARISH", "SHORT", "SELL", "BEAR"}:
        return "SHORT"
    return "NONE"


def _parse_time(value: Any) -> Optional[time]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.time()
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).time()
    except Exception:
        pass
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except Exception:
            continue
    return None


def _parse_date(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _signal(
    signal_id: str,
    status: str,
    direction: str = "NONE",
    score: float = 0.0,
    reason: str = "",
    **extra: Any,
) -> Dict[str, Any]:
    return {
        "id": signal_id,
        "status": status,
        "direction": direction,
        "score": round(score, 3),
        "reason": reason,
        "signal_only": signal_id != "three_thirty_effect",
        **extra,
    }


def calc_atr(rows: Iterable[Dict[str, Any]], period: int = 14) -> Optional[float]:
    clean = [row for row in rows or [] if _as_float(row.get("close"), 0) > 0]
    if len(clean) <= period:
        return None
    ranges: List[float] = []
    for idx in range(1, len(clean)):
        high = _as_float(clean[idx].get("high"), 0)
        low = _as_float(clean[idx].get("low"), 0)
        prev_close = _as_float(clean[idx - 1].get("close"), 0)
        if high <= 0 or low <= 0 or prev_close <= 0:
            continue
        ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(ranges) < period:
        return None
    return sum(ranges[-period:]) / period


def calc_vwap(rows: Iterable[Dict[str, Any]]) -> float:
    weighted = 0.0
    volume_sum = 0.0
    for row in rows or []:
        close = _as_float(row.get("close"), 0)
        high = _as_float(row.get("high"), close)
        low = _as_float(row.get("low"), close)
        volume = _as_float(row.get("volume"), 0)
        if close <= 0 or volume <= 0:
            continue
        weighted += ((high + low + close) / 3) * volume
        volume_sum += volume
    return weighted / volume_sum if volume_sum > 0 else 0.0


def analyze_liquidity_vacuum(rows: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    bars = [row for row in rows or [] if _as_float(row.get("close"), 0) > 0]
    lookback = int(max(5, _as_float(settings.get("PMO_LIQUIDITY_VACUUM_LOOKBACK_BARS", 20), 20)))
    min_gap_pct = max(0.01, _as_float(settings.get("PMO_LIQUIDITY_VACUUM_MIN_GAP_PCT", 0.35), 0.35))
    if len(bars) < lookback + 1:
        return _signal("liquidity_vacuum", "DATA_REQUIRED", reason=f"needs {lookback + 1}+ intraday bars", rows=len(bars))
    window = bars[-lookback - 1:-1]
    latest = bars[-1]
    closes = sorted({_as_float(row.get("close"), 0) for row in window if _as_float(row.get("close"), 0) > 0})
    if len(closes) < 2:
        return _signal("liquidity_vacuum", "DATA_REQUIRED", reason="not enough distinct closes", rows=len(bars))
    gaps: List[Dict[str, Any]] = []
    for lower, upper in zip(closes, closes[1:]):
        gap_pct = ((upper - lower) / lower) * 100 if lower > 0 else 0
        if gap_pct >= min_gap_pct:
            gaps.append({"lower": round(lower, 4), "upper": round(upper, 4), "gap_pct": round(gap_pct, 3)})
    price = _as_float(latest.get("close"), 0)
    active = next((gap for gap in gaps if gap["lower"] <= price <= gap["upper"]), None)
    if active:
        midpoint = (active["lower"] + active["upper"]) / 2
        direction = "LONG" if price <= midpoint else "SHORT"
        return _signal("liquidity_vacuum", "READY", direction, 1.0, f"price inside untraded zone {active['lower']} to {active['upper']}", zone=active, gap_count=len(gaps), rows=len(bars))
    nearest = sorted(gaps, key=lambda gap: min(abs(price - gap["lower"]), abs(price - gap["upper"])))[:1]
    return _signal("liquidity_vacuum", "WATCH" if gaps else "WAIT", "NONE", 0.4 if gaps else 0, f"{len(gaps)} vacuum zone(s) detected" if gaps else "no vacuum zone detected", nearest=nearest, gap_count=len(gaps), rows=len(bars))


def analyze_auction_probe(rows: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    bars = [row for row in rows or [] if _as_float(row.get("close"), 0) > 0]
    period = int(max(2, _as_float(settings.get("PMO_AUCTION_ATR_PERIOD", 14), 14)))
    band_mult = max(0.1, _as_float(settings.get("PMO_AUCTION_PROBE_ATR_MULT", 1.0), 1.0))
    if len(bars) <= period:
        return _signal("auction_vwap_atr", "DATA_REQUIRED", reason=f"needs {period + 1}+ bars", rows=len(bars))
    vwap = calc_vwap(bars)
    atr = calc_atr(bars, period)
    price = _as_float(bars[-1].get("close"), 0)
    if vwap <= 0 or not atr or price <= 0:
        return _signal("auction_vwap_atr", "DATA_REQUIRED", reason="missing VWAP/ATR/price", rows=len(bars))
    distance_atr = (price - vwap) / atr
    if distance_atr >= band_mult:
        return _signal("auction_vwap_atr", "READY", "SHORT", min(1.0, abs(distance_atr) / 2.0), f"upper auction probe {distance_atr:.2f} ATR above VWAP", vwap=round(vwap, 4), atr=round(atr, 4), distance_atr=round(distance_atr, 3))
    if distance_atr <= -band_mult:
        return _signal("auction_vwap_atr", "READY", "LONG", min(1.0, abs(distance_atr) / 2.0), f"lower auction probe {distance_atr:.2f} ATR below VWAP", vwap=round(vwap, 4), atr=round(atr, 4), distance_atr=round(distance_atr, 3))
    return _signal("auction_vwap_atr", "WAIT", "NONE", 0.0, f"inside value area {distance_atr:.2f} ATR from VWAP", vwap=round(vwap, 4), atr=round(atr, 4), distance_atr=round(distance_atr, 3))


def analyze_three_thirty_effect(candidate: Dict[str, Any], market_change_pct: Any, settings: Dict[str, Any], when: Any = None) -> Dict[str, Any]:
    if not bool(settings.get("PMO_330_EFFECT_ENABLED", True)):
        return _signal("three_thirty_effect", "OFF", reason="PMO_330_EFFECT_ENABLED is false", hard_block=False)
    current = _parse_time(when or candidate.get("timestamp") or candidate.get("time"))
    start_text = str(settings.get("PMO_330_EFFECT_START", "15:30"))
    start = _parse_time(start_text) or time(15, 30)
    if current is None:
        return _signal("three_thirty_effect", "DATA_REQUIRED", reason="needs ET timestamp or time", hard_block=False)
    side = _side(candidate.get("bias") or candidate.get("direction") or candidate.get("side"))
    market_change = _as_float(market_change_pct if market_change_pct not in (None, "") else candidate.get("market_change_pct", candidate.get("change_pct")), 0)
    trend_side = "LONG" if market_change > 0 else "SHORT" if market_change < 0 else "NONE"
    after_start = current >= start
    hard_block = after_start and side != "NONE" and side == trend_side and bool(settings.get("PMO_330_EFFECT_BLOCK_TREND_ENTRIES", True))
    status = "BLOCK" if hard_block else "CAUTION" if after_start else "CLEAR"
    reason = "trend-direction entry after 15:30 risks institutional rebalance" if hard_block else "after 15:30: counter-trend rebalance window active" if after_start else "before 15:30 rebalance window"
    return _signal("three_thirty_effect", status, "AGAINST_TREND" if after_start else "NONE", 1.0 if hard_block else 0.3 if after_start else 0.0, reason, hard_block=hard_block, time=current.strftime("%H:%M"), market_change_pct=round(market_change, 3), candidate_side=side, trend_side=trend_side, signal_only=False)


HEDGE_WORDS = {
    "approximately", "around", "about", "roughly", "believe", "believes", "think", "thinks",
    "may", "might", "could", "should", "potentially", "likely", "expect", "expects",
    "hope", "hopefully", "possible", "possibly", "somewhat", "kind of", "sort of",
}


def analyze_earnings_language(text: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    if not text:
        return _signal("earnings_language", "DATA_REQUIRED", reason="earnings call text unavailable")
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|\d+(?:\.\d+)?%?", text.lower())
    if not words:
        return _signal("earnings_language", "DATA_REQUIRED", reason="earnings call text has no tokens")
    hedge_count = sum(1 for word in words if word in HEDGE_WORDS)
    numeric_count = sum(1 for word in words if any(char.isdigit() for char in word))
    hedge_ratio = hedge_count / max(1, len(words))
    numeric_ratio = numeric_count / max(1, len(words))
    max_hedge = _as_float(settings.get("PMO_EARNINGS_LANGUAGE_MAX_HEDGE_RATIO", 0.035), 0.035)
    min_numeric = _as_float(settings.get("PMO_EARNINGS_LANGUAGE_MIN_NUMERIC_RATIO", 0.025), 0.025)
    if hedge_ratio > max_hedge and numeric_ratio < min_numeric:
        return _signal("earnings_language", "CAUTION", "BEARISH", min(1.0, hedge_ratio / max_hedge), f"high hedge language ratio {hedge_ratio:.3f} with low specificity", hedge_ratio=round(hedge_ratio, 4), numeric_ratio=round(numeric_ratio, 4), words=len(words))
    if numeric_ratio >= min_numeric and hedge_ratio <= max_hedge:
        return _signal("earnings_language", "READY", "BULLISH", min(1.0, numeric_ratio / min_numeric), f"specific language: numeric ratio {numeric_ratio:.3f}, hedge ratio {hedge_ratio:.3f}", hedge_ratio=round(hedge_ratio, 4), numeric_ratio=round(numeric_ratio, 4), words=len(words))
    return _signal("earnings_language", "NEUTRAL", "NONE", 0.0, f"mixed language: hedge {hedge_ratio:.3f}, numeric {numeric_ratio:.3f}", hedge_ratio=round(hedge_ratio, 4), numeric_ratio=round(numeric_ratio, 4), words=len(words))


def analyze_ask_side_prints(quotes: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    rows = [row for row in quotes or [] if isinstance(row, dict)]
    needed = int(max(2, _as_float(settings.get("PMO_ASK_PRINT_MIN_STREAK", 3), 3)))
    streak = 0
    best = 0
    for row in rows:
        price = _as_float(row.get("price") or row.get("trade_price") or row.get("last"), 0)
        ask = _as_float(row.get("ask") or row.get("ask_price"), 0)
        bid = _as_float(row.get("bid") or row.get("bid_price"), 0)
        side = str(row.get("side") or row.get("print_side") or "").upper()
        at_ask = side in {"ASK", "BUY", "A"} or (ask > 0 and price >= ask) or (ask > 0 and bid > 0 and price >= (bid + ask) / 2 and abs(price - ask) <= abs(price - bid))
        if at_ask:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    if best >= needed:
        return _signal("ask_side_prints", "READY", "LONG", min(1.0, best / max(needed, 1)), f"{best} consecutive ask-side print(s)", streak=best, required=needed, rows=len(rows))
    return _signal("ask_side_prints", "WAIT" if rows else "DATA_REQUIRED", "NONE", 0.0, f"best ask-side streak {best}/{needed}" if rows else "quote/print rows unavailable", streak=best, required=needed, rows=len(rows))


def analyze_pead(symbol: str, earnings_rows: Iterable[Dict[str, Any]], settings: Dict[str, Any], as_of: Any = None) -> Dict[str, Any]:
    clean = str(symbol or "").upper().strip()
    rows = [row for row in earnings_rows or [] if isinstance(row, dict) and (_symbol(row) == clean or not _symbol(row))]
    window = int(max(1, _as_float(settings.get("PMO_PEAD_WINDOW_DAYS", 11), 11)))
    current = _parse_date(as_of) or datetime.now()
    best: Optional[Dict[str, Any]] = None
    best_days = 9999
    for row in rows:
        dt = _parse_date(row.get("earnings_date") or row.get("date") or row.get("reported_at"))
        if not dt:
            continue
        days = (current.date() - dt.date()).days
        if 0 <= days <= window and days < best_days:
            best = row
            best_days = days
    if not best:
        return _signal("pead", "DATA_REQUIRED" if not rows else "WAIT", reason=f"no earnings event inside {window}-day PEAD window", rows=len(rows))
    surprise = _as_float(best.get("surprise_pct") or best.get("eps_surprise_pct") or best.get("beat_pct"), 0)
    beat = str(best.get("result") or best.get("earnings_result") or "").upper()
    direction = "LONG" if surprise > 0 or "BEAT" in beat else "SHORT" if surprise < 0 or "MISS" in beat else "NONE"
    status = "READY" if direction != "NONE" else "WATCH"
    return _signal("pead", status, direction, min(1.0, abs(surprise) / 10.0) if surprise else 0.4, f"day {best_days}/{window} after {'positive' if direction == 'LONG' else 'negative' if direction == 'SHORT' else 'mixed'} earnings", days_since=best_days, window_days=window, surprise_pct=round(surprise, 3), event=best)


def analyze_volatility_risk_premium(iv_rows: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    rows = [row for row in iv_rows or [] if isinstance(row, dict)]
    if not rows:
        return _signal("volatility_risk_premium", "DATA_REQUIRED", reason="IV/rank rows unavailable")
    latest = rows[-1]
    iv_rank = _as_float(latest.get("iv_rank") or latest.get("iv_percentile") or latest.get("iv_rank_pct"), -1)
    implied = _as_float(latest.get("implied_volatility") or latest.get("iv"), 0)
    realized = _as_float(latest.get("realized_volatility") or latest.get("rv"), 0)
    min_rank = _as_float(settings.get("PMO_VRP_MIN_IV_RANK", 50), 50)
    spread = implied - realized if implied > 0 and realized > 0 else 0
    if iv_rank >= min_rank or spread > 0:
        score = max(iv_rank / 100 if iv_rank >= 0 else 0, min(1.0, spread / max(implied, 1))) 
        return _signal("volatility_risk_premium", "READY", "MEAN_REVERSION", score, f"IV risk premium elevated: IV rank {iv_rank:g}, IV-RV spread {spread:.3f}", iv_rank=round(iv_rank, 3), implied_volatility=round(implied, 4), realized_volatility=round(realized, 4), stop_context="WIDEN_STOPS")
    return _signal("volatility_risk_premium", "WAIT", "NONE", 0.0, f"IV rank {iv_rank:g} below {min_rank:g}", iv_rank=round(iv_rank, 3), implied_volatility=round(implied, 4), realized_volatility=round(realized, 4))


def analyze_institutional_signals(
    symbol: str,
    settings: Optional[Dict[str, Any]] = None,
    *,
    bars: Optional[List[Dict[str, Any]]] = None,
    candidate: Optional[Dict[str, Any]] = None,
    quotes: Optional[List[Dict[str, Any]]] = None,
    earnings_rows: Optional[List[Dict[str, Any]]] = None,
    iv_rows: Optional[List[Dict[str, Any]]] = None,
    earnings_text: str = "",
    market_change_pct: Any = None,
    now_value: Any = None,
) -> Dict[str, Any]:
    settings = settings or {}
    candidate = dict(candidate or {})
    bars = bars or []
    signals = {
        "liquidity_vacuum": analyze_liquidity_vacuum(bars, settings),
        "auction_vwap_atr": analyze_auction_probe(bars, settings),
        "three_thirty_effect": analyze_three_thirty_effect(candidate, market_change_pct, settings, when=now_value),
        "earnings_language": analyze_earnings_language(earnings_text, settings),
        "ask_side_prints": analyze_ask_side_prints(quotes or [], settings),
        "pead": analyze_pead(symbol, earnings_rows or [], settings, as_of=now_value),
        "volatility_risk_premium": analyze_volatility_risk_premium(iv_rows or [], settings),
    }
    ready = [item for item in signals.values() if item.get("status") == "READY"]
    blockers = [item.get("reason", "") for item in signals.values() if item.get("hard_block")]
    long_count = sum(1 for item in ready if item.get("direction") in {"LONG", "BULLISH", "MEAN_REVERSION"})
    short_count = sum(1 for item in ready if item.get("direction") in {"SHORT", "BEARISH", "MEAN_REVERSION"})
    consensus = "BLOCK" if blockers else "BULLISH" if long_count > short_count and long_count >= 2 else "BEARISH" if short_count > long_count and short_count >= 2 else "MIXED" if ready else "DATA_BUILDING"
    return {
        "ok": True,
        "enabled": bool(settings.get("ENABLE_PMO_INSTITUTIONAL_SIGNALS", True)),
        "symbol": str(symbol or "").upper().strip(),
        "mode": "SIGNAL_LAYER",
        "read_only": True,
        "score_influence": bool(settings.get("PMO_INSTITUTIONAL_SCORE_INFLUENCE", False)),
        "live_unlocked": False,
        "orders_placed": False,
        "settings_changed": False,
        "consensus": consensus,
        "ready_count": len(ready),
        "blockers": blockers,
        "signals": signals,
        "journal": {
            "inst_consensus": consensus,
            "inst_ready_count": len(ready),
            "inst_blockers": " | ".join(blockers),
            "inst_liquidity_vacuum": signals["liquidity_vacuum"].get("status"),
            "inst_auction_probe": signals["auction_vwap_atr"].get("status"),
            "inst_330_effect": signals["three_thirty_effect"].get("status"),
            "inst_ask_prints": signals["ask_side_prints"].get("status"),
            "inst_pead": signals["pead"].get("status"),
            "inst_vrp": signals["volatility_risk_premium"].get("status"),
        },
    }

