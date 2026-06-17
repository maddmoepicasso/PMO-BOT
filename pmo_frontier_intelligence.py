"""
PMO frontier intelligence layer.

Read-only research adapters for:
- market consciousness
- narrative momentum
- reflexivity loops
- synthetic alpha from engine divergence
- multi-year temporal memory
- Monte Carlo pre-trade simulation
- supervised self-modification proposals

This module never places orders, unlocks live trading, or mutates settings.
"""

from __future__ import annotations

import hashlib
import math
import random
import statistics
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "N/A"):
            return default
        text = str(value).strip().replace(",", "")
        if text.endswith("%"):
            text = text[:-1]
        return float(text)
    except Exception:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(_float(value, default))
    except Exception:
        return default


def _text(value: Any) -> str:
    return str(value or "").strip().upper()


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _symbol(row: Dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker") or row.get("underlying"))


def _is_win(row: Dict[str, Any]) -> bool:
    status = _text(row.get("status") or row.get("result") or row.get("outcome"))
    pnl = _float(row.get("pnl") or row.get("pnl_usd") or row.get("profit_loss") or row.get("realized_pnl"), 0.0)
    return "WIN" in status or pnl > 0


def _is_loss(row: Dict[str, Any]) -> bool:
    status = _text(row.get("status") or row.get("result") or row.get("outcome"))
    pnl = _float(row.get("pnl") or row.get("pnl_usd") or row.get("profit_loss") or row.get("realized_pnl"), 0.0)
    return "LOSS" in status or pnl < 0


def _close(row: Dict[str, Any]) -> float:
    return _float(row.get("close") or row.get("c") or row.get("price") or row.get("last"), 0.0)


def _pct_change(start: float, end: float) -> float:
    return ((end - start) / start * 100.0) if start > 0 else 0.0


def _signal(signal_id: str, status: str, score: float = 0.0, direction: str = "NEUTRAL", reason: str = "", **extra: Any) -> Dict[str, Any]:
    return {
        "id": signal_id,
        "status": status,
        "score": round(max(-100.0, min(100.0, score)), 4),
        "direction": direction,
        "reason": reason,
        **extra,
    }


def _zscore(values: List[float], latest: float) -> float:
    clean = [value for value in values if math.isfinite(value)]
    if len(clean) < 3:
        return 0.0
    mean = statistics.fmean(clean)
    stdev = statistics.pstdev(clean)
    if stdev <= 0:
        return 0.0
    return (latest - mean) / stdev


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def market_consciousness(rows: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    data = [dict(row) for row in rows or [] if isinstance(row, dict)]
    if not data:
        return _signal("market_consciousness", "DATA_REQUIRED", reason="macro belief rows unavailable", components={})
    latest = data[-1]
    credit_spread = _float(latest.get("credit_spread_bps") or latest.get("high_yield_spread_bps"), 0.0)
    yield_curve = _float(latest.get("yield_curve_10y2y_bps") or latest.get("yield_curve_bps"), 0.0)
    dollar_change = _float(latest.get("dxy_change_pct") or latest.get("usd_change_pct"), 0.0)
    cot_net = _float(latest.get("cftc_net_position_z") or latest.get("cot_net_position_z"), 0.0)
    breadth = _float(latest.get("breadth_pct"), 50.0)
    vix_change = _float(latest.get("vix_change_pct"), 0.0)
    credit_stress_bps = _float(settings.get("PMO_FRONTIER_CREDIT_STRESS_BPS"), 450.0)
    curve_recession_bps = _float(settings.get("PMO_FRONTIER_RECESSION_CURVE_BPS"), -50.0)
    score = 0.0
    score += max(-25.0, min(25.0, (breadth - 50.0) * 0.8))
    score += -25.0 if credit_spread >= credit_stress_bps else 10.0 if credit_spread > 0 and credit_spread <= credit_stress_bps * 0.55 else 0.0
    score += -15.0 if yield_curve <= curve_recession_bps else 8.0 if yield_curve >= 50 else 0.0
    score += -10.0 if dollar_change > 0.6 else 8.0 if dollar_change < -0.4 else 0.0
    score += max(-12.0, min(12.0, cot_net * 4.0))
    score += -12.0 if vix_change > 8 else 8.0 if vix_change < -5 else 0.0
    direction = "RISK_ON" if score >= 15 else "RISK_OFF" if score <= -15 else "MIXED"
    status = "READY"
    return _signal(
        "market_consciousness",
        status,
        score,
        direction,
        "unified belief model from credit, curve, dollar, CFTC positioning, breadth, and VIX context",
        components={
            "credit_spread_bps": credit_spread,
            "yield_curve_10y2y_bps": yield_curve,
            "dxy_change_pct": dollar_change,
            "cftc_net_position_z": cot_net,
            "breadth_pct": breadth,
            "vix_change_pct": vix_change,
        },
        rows=len(data),
    )


def narrative_momentum(symbol: str, rows: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    clean_symbol = _text(symbol)
    data = [dict(row) for row in rows or [] if isinstance(row, dict) and (_symbol(row) in {"", clean_symbol} or clean_symbol in _text(row.get("symbols")))]
    if not data:
        return _signal("narrative_momentum", "DATA_REQUIRED", reason="narrative rows unavailable", narratives=[])
    min_ratio = _float(settings.get("PMO_FRONTIER_NARRATIVE_MIN_VELOCITY_RATIO"), 2.5)
    min_mentions = _int(settings.get("PMO_FRONTIER_NARRATIVE_MIN_MENTIONS"), 20)
    hits: List[Dict[str, Any]] = []
    for row in data:
        current = _float(row.get("mentions") or row.get("current_mentions") or row.get("count"), 0.0)
        baseline = max(1.0, _float(row.get("baseline_mentions") or row.get("baseline") or row.get("avg_mentions"), 1.0))
        velocity = current / baseline
        sentiment = _float(row.get("sentiment") or row.get("sentiment_score"), 0.0)
        theme = str(row.get("theme") or row.get("phrase") or row.get("narrative") or "UNKNOWN")
        score = velocity * max(0.25, 1.0 + sentiment)
        if current >= min_mentions and velocity >= min_ratio:
            hits.append({
                "theme": theme,
                "mentions": round(current, 2),
                "baseline": round(baseline, 2),
                "velocity_ratio": round(velocity, 4),
                "sentiment": round(sentiment, 4),
                "score": round(score, 4),
            })
    hits.sort(key=lambda row: _float(row.get("score"), 0), reverse=True)
    if not hits:
        return _signal("narrative_momentum", "BUILDING", 0.0, "NEUTRAL", "no narrative velocity above threshold", narratives=[])
    top = hits[0]
    direction = "BULLISH" if _float(top.get("sentiment"), 0) >= -0.15 else "BEARISH"
    score = min(100.0, _float(top.get("velocity_ratio"), 0) * 12.0)
    return _signal("narrative_momentum", "READY", score, direction, f"narrative velocity spike: {top.get('theme')}", narratives=hits[:8])


def reflexivity_loop(symbol: str, bars: Iterable[Dict[str, Any]], news_rows: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    data = [dict(row) for row in bars or [] if isinstance(row, dict) and _close(row) > 0]
    if len(data) < 8:
        return _signal("reflexivity", "DATA_REQUIRED", reason="needs at least 8 bars", bars=len(data))
    first = _close(data[0])
    last = _close(data[-1])
    move = _pct_change(first, last)
    volumes = [_float(row.get("volume"), 0) for row in data]
    avg_prior = statistics.fmean(volumes[:-1]) if len(volumes) > 1 and any(volumes[:-1]) else 0.0
    vol_ratio = volumes[-1] / max(1.0, avg_prior)
    news = [row for row in news_rows or [] if isinstance(row, dict) and (_symbol(row) in {"", _text(symbol)})]
    catalyst_count = sum(1 for row in news if any(token in _text(row.get("headline") or row.get("title") or row.get("event")) for token in ("RAISES", "UPGRADE", "AI", "DEAL", "OFFERING", "ACQUISITION", "GUIDANCE", "BUYBACK")))
    loop_threshold = _float(settings.get("PMO_FRONTIER_REFLEXIVITY_MIN_MOVE_PCT"), 4.0)
    break_threshold = _float(settings.get("PMO_FRONTIER_REFLEXIVITY_BREAK_REVERSAL_PCT"), 2.0)
    recent_high = max(_close(row) for row in data[-5:])
    pullback = _pct_change(recent_high, last)
    if move >= loop_threshold and vol_ratio >= 1.5:
        status = "LOOP_ACTIVE"
        direction = "BULLISH"
        reason = "price and volume are reinforcing the story"
        score = min(100.0, move * 8.0 + min(20.0, catalyst_count * 5.0))
    elif move >= loop_threshold and pullback <= -break_threshold:
        status = "LOOP_BREAKING"
        direction = "CAUTION"
        reason = "reflexive move is reversing from recent high"
        score = -min(100.0, abs(pullback) * 18.0)
    else:
        status = "WATCH"
        direction = "NEUTRAL"
        reason = "no strong self-reinforcing loop detected"
        score = 0.0
    return _signal("reflexivity", status, score, direction, reason, move_pct=round(move, 4), volume_ratio=round(vol_ratio, 4), catalyst_count=catalyst_count, pullback_from_recent_high_pct=round(pullback, 4))


def engine_divergence(candidate: Dict[str, Any], history_rows: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    fields = settings.get("PMO_FRONTIER_DIVERGENCE_FIELDS") or [
        "score",
        "relative_volume",
        "edge_score",
        "intel_score",
        "ml_score",
        "sentiment_score",
        "elite_agree_ratio",
        "inst_ready_count",
        "deep_size_mult",
    ]
    rows = [dict(row) for row in history_rows or [] if isinstance(row, dict)]
    current_values = {field: _float(candidate.get(field), math.nan) for field in fields}
    pairs: List[Dict[str, Any]] = []
    for idx, left in enumerate(fields):
        for right in fields[idx + 1:]:
            lv = current_values.get(left)
            rv = current_values.get(right)
            if lv is None or rv is None or not math.isfinite(lv) or not math.isfinite(rv):
                continue
            diff = lv - rv
            historical = []
            for row in rows[-80:]:
                lhv = _float(row.get(left), math.nan)
                rhv = _float(row.get(right), math.nan)
                if math.isfinite(lhv) and math.isfinite(rhv):
                    historical.append(lhv - rhv)
            z = abs(_zscore(historical, diff)) if historical else 0.0
            threshold = _float(settings.get("PMO_FRONTIER_DIVERGENCE_Z_THRESHOLD"), 2.0)
            if z >= threshold:
                pairs.append({"left": left, "right": right, "current_diff": round(diff, 4), "zscore": round(z, 4)})
    pairs.sort(key=lambda row: _float(row.get("zscore"), 0), reverse=True)
    status = "DIVERGENCE_ALERT" if pairs else ("BUILDING" if len(rows) < 20 else "CLEAR")
    score = min(100.0, sum(_float(row.get("zscore"), 0) for row in pairs[:5]) * 12.0)
    return _signal("engine_divergence", status, score, "ALERT" if pairs else "NEUTRAL", "usually related engines are disagreeing beyond normal range" if pairs else "engine pair divergence inside normal range", pairs=pairs[:10], history_rows=len(rows))


def multi_year_temporal_memory(current: Dict[str, Any], fingerprints: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    fields = settings.get("PMO_FRONTIER_MEMORY_FIELDS") or ["breadth_pct", "vix", "vix_change_pct", "credit_spread_bps", "yield_curve_10y2y_bps", "qqq_change_pct", "xlf_change_pct", "tlt_change_pct", "gld_change_pct"]
    current_vec = [_float(current.get(field), 0.0) for field in fields]
    rows = [dict(row) for row in fingerprints or [] if isinstance(row, dict)]
    if not rows:
        return _signal("temporal_memory", "DATA_REQUIRED", reason="historical macro fingerprint library unavailable", matches=[])
    matches: List[Dict[str, Any]] = []
    for row in rows:
        vec = [_float(row.get(field), 0.0) for field in fields]
        similarity = _cosine(current_vec, vec)
        matches.append({
            "label": row.get("label") or row.get("period") or row.get("date") or "UNKNOWN",
            "similarity": round(similarity, 4),
            "forward_5d_pct": _float(row.get("forward_5d_pct"), 0.0),
            "forward_20d_pct": _float(row.get("forward_20d_pct"), 0.0),
            "note": row.get("note") or "",
        })
    matches.sort(key=lambda row: _float(row.get("similarity"), 0), reverse=True)
    min_similarity = _float(settings.get("PMO_FRONTIER_MEMORY_MIN_SIMILARITY"), 0.72)
    top = matches[0] if matches else {}
    status = "MATCH" if _float(top.get("similarity"), 0) >= min_similarity else "LOW_SIMILARITY"
    forward = _float(top.get("forward_20d_pct"), 0.0)
    direction = "BULLISH" if forward > 1 else "BEARISH" if forward < -1 else "NEUTRAL"
    score = _float(top.get("similarity"), 0) * (1 if direction != "BEARISH" else -1) * 100.0
    return _signal("temporal_memory", status, score, direction, "current macro fingerprint compared with historical turning-point library", matches=matches[:5], fields=fields)


def monte_carlo_trade_simulation(symbol: str, bars: Iterable[Dict[str, Any]], candidate: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    data = [dict(row) for row in bars or [] if isinstance(row, dict) and _close(row) > 0]
    paths = int(max(100, min(5000, _float(settings.get("PMO_FRONTIER_MONTE_CARLO_PATHS"), 1000))))
    horizon = int(max(5, min(240, _float(settings.get("PMO_FRONTIER_MONTE_CARLO_HORIZON_MINUTES"), 30))))
    if len(data) < 8:
        return _signal("monte_carlo", "DATA_REQUIRED", reason="needs 8+ bars for realized volatility", paths=0, recommended_size_multiplier=0.35)
    closes = [_close(row) for row in data]
    returns = [_pct_change(closes[idx - 1], closes[idx]) for idx in range(1, len(closes)) if closes[idx - 1] > 0]
    if not returns:
        return _signal("monte_carlo", "DATA_REQUIRED", reason="bar returns unavailable", paths=0, recommended_size_multiplier=0.35)
    mu = statistics.fmean(returns)
    sigma = statistics.pstdev(returns) or max(0.05, abs(mu))
    side = _text(candidate.get("side") or candidate.get("bias") or candidate.get("direction"))
    direction = -1.0 if side in {"SHORT", "PUT", "PUT_BIAS", "BEARISH", "SELL"} else 1.0
    target_pct = abs(_float(candidate.get("target_pct") or settings.get("PMO_DEFAULT_TAKE_PROFIT_PCT"), 3.0))
    stop_pct = abs(_float(candidate.get("stop_pct") or settings.get("PMO_DEFAULT_STOP_LOSS_PCT"), 4.0))
    seed_material = f"{symbol}|{len(data)}|{closes[-1]:.4f}|{paths}|{horizon}".encode("utf-8")
    seed = int(hashlib.sha256(seed_material).hexdigest()[:12], 16)
    rng = random.Random(seed)
    wins = 0
    losses = 0
    tail_events = 0
    max_loss = 0.0
    steps = max(1, horizon // 5)
    for _ in range(paths):
        cumulative = 0.0
        hit = "OPEN"
        for _step in range(steps):
            shock = rng.gauss(mu, sigma) + rng.choice([0.0, 0.0, 0.0, -sigma * 2.5, sigma * 2.0])
            directional_return = shock * direction
            cumulative += directional_return
            max_loss = min(max_loss, cumulative)
            if cumulative >= target_pct:
                hit = "WIN"
                break
            if cumulative <= -stop_pct:
                hit = "LOSS"
                break
            if cumulative <= -stop_pct * 1.6:
                tail_events += 1
        if hit == "WIN":
            wins += 1
        elif hit == "LOSS":
            losses += 1
    win_prob = wins / paths if paths else 0.0
    loss_prob = losses / paths if paths else 0.0
    tail_prob = tail_events / paths if paths else 0.0
    if tail_prob >= _float(settings.get("PMO_FRONTIER_TAIL_RISK_MAX_PROB"), 0.05):
        size = 0.10
        status = "TAIL_RISK"
    elif win_prob >= _float(settings.get("PMO_FRONTIER_MONTE_CARLO_MIN_WIN_PROB"), 0.60):
        size = min(1.0, max(0.35, win_prob))
        status = "FAVORABLE"
    else:
        size = 0.35
        status = "LOW_CONFIDENCE"
    score = (win_prob - loss_prob - tail_prob * 2.0) * 100.0
    return _signal("monte_carlo", status, score, "SIZE_GUIDANCE", "pre-trade path simulation converts uncertainty into position-size guidance", paths=paths, horizon_minutes=horizon, win_probability=round(win_prob, 4), loss_probability=round(loss_prob, 4), tail_risk_probability=round(tail_prob, 4), recommended_size_multiplier=round(size, 4), max_simulated_loss_pct=round(max_loss, 4), seed=seed)


def supervised_self_modification(trades: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    clean = [dict(row) for row in trades or [] if isinstance(row, dict) and (_is_win(row) or _is_loss(row))]
    window = int(max(5, _float(settings.get("PMO_FRONTIER_SELF_MOD_WINDOW_TRADES"), 10)))
    if len(clean) < window:
        return _signal("self_modification", "DATA_BUILDING", reason=f"needs {window} closed trades before proposing changes", proposals=[], rows=len(clean))
    recent = clean[-window:]
    proposals: List[Dict[str, Any]] = []
    losses = [row for row in recent if _is_loss(row)]
    wins = [row for row in recent if _is_win(row)]
    wr = len(wins) / max(1, len(recent))
    stop_values = [_float(row.get("max_drawdown_pct") or row.get("mae_pct") or row.get("drawdown_pct"), 0.0) for row in losses]
    stop_values = [abs(value) for value in stop_values if value]
    if len(losses) >= max(3, window // 3) and stop_values:
        median_stop = statistics.median(stop_values)
        proposals.append({
            "id": "review_stop_loss",
            "status": "PENDING_OWNER_REVIEW",
            "parameter": "PMO_DEFAULT_STOP_LOSS_PCT",
            "current": settings.get("PMO_DEFAULT_STOP_LOSS_PCT"),
            "proposed": round(max(1.0, min(8.0, median_stop + 0.2)), 2),
            "evidence": f"{len(losses)}/{window} recent losses; median adverse excursion {median_stop:.2f}%",
            "requires_approval": True,
        })
    hold_values = [_float(row.get("hold_minutes"), 0.0) for row in wins if _float(row.get("hold_minutes"), 0.0) > 0]
    if len(hold_values) >= 3:
        median_hold = statistics.median(hold_values)
        current_hold = _float(settings.get("PMO_PAPER_MAX_HOLD_MINUTES"), 90.0)
        if median_hold < current_hold * 0.5:
            proposals.append({
                "id": "review_max_hold",
                "status": "PENDING_OWNER_REVIEW",
                "parameter": "PMO_PAPER_MAX_HOLD_MINUTES",
                "current": current_hold,
                "proposed": int(max(10, median_hold * 1.5)),
                "evidence": f"recent winners mature faster; median winning hold {median_hold:.1f} minutes",
                "requires_approval": True,
            })
    if wr < _float(settings.get("PMO_FRONTIER_SELF_MOD_MIN_RECENT_WR"), 0.45):
        proposals.append({
            "id": "review_entry_gate",
            "status": "PENDING_OWNER_REVIEW",
            "parameter": "PMO_PAPER_EXECUTOR_MIN_SCORE",
            "current": settings.get("PMO_PAPER_EXECUTOR_MIN_SCORE"),
            "proposed": _float(settings.get("PMO_PAPER_EXECUTOR_MIN_SCORE"), 65.0) + 5.0,
            "evidence": f"recent win rate {wr:.1%} below frontier review threshold",
            "requires_approval": True,
        })
    status = "PROPOSAL_READY" if proposals else "NO_CHANGE"
    return _signal("self_modification", status, -10.0 if proposals else 0.0, "OWNER_REVIEW", "generates specific parameter proposals without applying them", rows=len(clean), window=window, recent_win_rate=round(wr, 4), proposals=proposals[:6], settings_changed=False)


def frontier_operational_guidance(signals: Dict[str, Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    mc = signals.get("market_consciousness", {})
    narrative = signals.get("narrative_momentum", {})
    reflex = signals.get("reflexivity", {})
    divergence = signals.get("engine_divergence", {})
    memory = signals.get("temporal_memory", {})
    monte = signals.get("monte_carlo", {})
    self_mod = signals.get("self_modification", {})
    blockers = []
    if mc.get("direction") == "RISK_OFF":
        blockers.append("market_consciousness_risk_off")
    if divergence.get("status") == "DIVERGENCE_ALERT":
        blockers.append("engine_divergence")
    if reflex.get("status") == "LOOP_BREAKING":
        blockers.append("reflexivity_break")
    if monte.get("status") == "TAIL_RISK":
        blockers.append("monte_carlo_tail_risk")
    size = _float(monte.get("recommended_size_multiplier"), 1.0)
    if mc.get("direction") == "RISK_OFF":
        size = min(size, 0.50)
    if divergence.get("status") == "DIVERGENCE_ALERT":
        size = min(size, _float(settings.get("PMO_FRONTIER_DIVERGENCE_SIZE_MULTIPLIER"), 0.65))
    if self_mod.get("status") == "PROPOSAL_READY":
        size = min(size, 0.75)
    score_mod = 0.0
    if narrative.get("direction") == "BULLISH":
        score_mod += min(4.0, _float(narrative.get("score"), 0) / 25.0)
    if reflex.get("status") == "LOOP_ACTIVE":
        score_mod += min(4.0, _float(reflex.get("score"), 0) / 25.0)
    if mc.get("direction") == "RISK_OFF":
        score_mod -= 4.0
    if memory.get("direction") == "BEARISH":
        score_mod -= 2.0
    return {
        "status": "CAUTION" if blockers else "NORMAL",
        "position_size_multiplier": round(max(0.1, min(1.0, size)), 4),
        "score_mod_recommendation": round(max(-8.0, min(8.0, score_mod)), 4),
        "score_mod_applied": False,
        "blockers": blockers,
        "market_belief": mc.get("direction", "UNKNOWN"),
        "narrative_direction": narrative.get("direction", "NEUTRAL"),
        "reflexivity_status": reflex.get("status", "DATA_REQUIRED"),
        "monte_carlo_status": monte.get("status", "DATA_REQUIRED"),
        "proposal_count": len((self_mod.get("proposals") or []) if isinstance(self_mod.get("proposals"), list) else []),
        "reason": "Read-only frontier guidance: belief, narrative, reflexivity, divergence, memory, simulation, and supervised proposals.",
    }


def analyze_frontier_intelligence(
    symbol: str,
    settings: Dict[str, Any],
    *,
    candidate: Optional[Dict[str, Any]] = None,
    bars: Optional[List[Dict[str, Any]]] = None,
    trades: Optional[List[Dict[str, Any]]] = None,
    macro_rows: Optional[List[Dict[str, Any]]] = None,
    narrative_rows: Optional[List[Dict[str, Any]]] = None,
    news_rows: Optional[List[Dict[str, Any]]] = None,
    engine_history_rows: Optional[List[Dict[str, Any]]] = None,
    fingerprints: Optional[List[Dict[str, Any]]] = None,
    now_value: Any = None,
) -> Dict[str, Any]:
    clean_symbol = _text(symbol or "SPY")
    candidate = dict(candidate or {})
    candidate.setdefault("symbol", clean_symbol)
    bars = bars or []
    trades = trades or []
    macro_rows = macro_rows or []
    narrative_rows = narrative_rows or []
    news_rows = news_rows or []
    engine_history_rows = engine_history_rows or []
    current_macro = dict(macro_rows[-1]) if macro_rows else dict(candidate)
    signals = {
        "market_consciousness": market_consciousness(macro_rows, settings),
        "narrative_momentum": narrative_momentum(clean_symbol, narrative_rows, settings),
        "reflexivity": reflexivity_loop(clean_symbol, bars, news_rows, settings),
        "engine_divergence": engine_divergence(candidate, engine_history_rows, settings),
        "temporal_memory": multi_year_temporal_memory(current_macro, fingerprints or [], settings),
        "monte_carlo": monte_carlo_trade_simulation(clean_symbol, bars, candidate, settings),
        "self_modification": supervised_self_modification(trades, settings),
    }
    guidance = frontier_operational_guidance(signals, settings)
    alert_keys = [key for key, value in signals.items() if str(value.get("status", "")).upper() in {"DIVERGENCE_ALERT", "TAIL_RISK", "LOOP_BREAKING", "PROPOSAL_READY"}]
    ready_statuses = {"READY", "FAVORABLE", "LOW_CONFIDENCE", "TAIL_RISK", "MATCH", "LOW_SIMILARITY", "CLEAR", "WATCH", "LOOP_ACTIVE", "LOOP_BREAKING", "NO_CHANGE", "PROPOSAL_READY"}
    ready_count = sum(1 for value in signals.values() if str(value.get("status", "")).upper() in ready_statuses)
    status = "ATTENTION_REQUIRED" if alert_keys else "READY" if ready_count >= 4 else "DATA_BUILDING"
    return {
        "ok": True,
        "enabled": bool(settings.get("ENABLE_PMO_FRONTIER_INTELLIGENCE", True)),
        "symbol": clean_symbol,
        "status": status,
        "mode": "READ_ONLY_FRONTIER_INTELLIGENCE",
        "read_only": True,
        "score_influence": bool(settings.get("PMO_FRONTIER_SCORE_INFLUENCE", False)),
        "orders_placed": False,
        "live_unlocked": False,
        "settings_changed": False,
        "now": str(now_value or ""),
        "ready_count": ready_count,
        "alert_keys": alert_keys,
        "recommended_position_size_multiplier": guidance.get("position_size_multiplier", 1.0),
        "operational_guidance": guidance,
        "signals": signals,
        "journal": {
            "frontier_status": status,
            "frontier_ready_count": ready_count,
            "frontier_alerts": ",".join(alert_keys),
            "frontier_size_mult": guidance.get("position_size_multiplier", 1.0),
            "frontier_score_mod_rec": guidance.get("score_mod_recommendation", 0.0),
            "frontier_market_belief": guidance.get("market_belief", "UNKNOWN"),
            "frontier_narrative": guidance.get("narrative_direction", "NEUTRAL"),
            "frontier_reflexivity": guidance.get("reflexivity_status", "DATA_REQUIRED"),
            "frontier_monte_carlo": guidance.get("monte_carlo_status", "DATA_REQUIRED"),
            "frontier_self_mod_proposals": guidance.get("proposal_count", 0),
        },
    }
