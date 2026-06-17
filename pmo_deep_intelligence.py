from __future__ import annotations

from datetime import datetime, timedelta
from math import sqrt
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _symbol(row: Dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").strip().upper()


def _row_time(row: Dict[str, Any]) -> Optional[datetime]:
    for field in ("exit_timestamp", "closed_at", "filled_at", "timestamp", "entry_timestamp", "created_at", "time"):
        ts = _parse_time(row.get(field))
        if ts:
            return ts
    return None


def _is_win(row: Dict[str, Any]) -> bool:
    status = str(row.get("status") or row.get("result") or row.get("outcome") or "").upper()
    pnl = _safe_float(row.get("pnl") or row.get("pnl_usd") or row.get("profit_loss") or row.get("realized_pnl"), 0)
    return "WIN" in status or pnl > 0


def _is_loss(row: Dict[str, Any]) -> bool:
    status = str(row.get("status") or row.get("result") or row.get("outcome") or "").upper()
    pnl = _safe_float(row.get("pnl") or row.get("pnl_usd") or row.get("profit_loss") or row.get("realized_pnl"), 0)
    return "LOSS" in status or pnl < 0


def _close(row: Dict[str, Any]) -> float:
    return _safe_float(row.get("close") or row.get("price") or row.get("last") or row.get("exit_price") or row.get("entry_price"), 0)


def _bar_time(row: Dict[str, Any]) -> Optional[datetime]:
    for field in ("timestamp", "time", "t", "datetime"):
        ts = _parse_time(row.get(field))
        if ts:
            return ts
    return None


def _pct_change(start: float, end: float) -> float:
    if start <= 0:
        return 0.0
    return ((end - start) / start) * 100.0


def _wins_losses(trades: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    wins = 0
    losses = 0
    for row in trades:
        if _is_win(row):
            wins += 1
        elif _is_loss(row):
            losses += 1
    return wins, losses


def concept_drift_monitor(trades: List[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    window = int(max(3, _safe_float(settings.get("PMO_CONCEPT_DRIFT_ROLLING_WINDOW"), 15)))
    drop = max(0.01, _safe_float(settings.get("PMO_CONCEPT_DRIFT_ALERT_DROP"), 0.15))
    size_cut = max(0.05, min(1.0, _safe_float(settings.get("PMO_CONCEPT_DRIFT_SIZE_MULTIPLIER"), 0.65)))
    clean = [row for row in trades if _is_win(row) or _is_loss(row)]
    wins, losses = _wins_losses(clean)
    closed = wins + losses
    cumulative_wr = wins / closed if closed else 0.0
    rolling_rows = clean[-window:]
    rolling_wins, rolling_losses = _wins_losses(rolling_rows)
    rolling_closed = rolling_wins + rolling_losses
    rolling_wr = rolling_wins / rolling_closed if rolling_closed else 0.0
    drift = bool(rolling_closed >= window and (cumulative_wr - rolling_wr) >= drop)
    return {
        "id": "concept_drift",
        "status": "ALERT" if drift else ("READY" if closed >= window else "DATA_BUILDING"),
        "closed": closed,
        "rolling_window": window,
        "rolling_closed": rolling_closed,
        "cumulative_win_rate": round(cumulative_wr, 4),
        "rolling_win_rate": round(rolling_wr, 4),
        "drop_from_cumulative": round(cumulative_wr - rolling_wr, 4),
        "alert_drop": drop,
        "position_size_multiplier": size_cut if drift else 1.0,
        "reason": (
            f"rolling WR fell at least {drop:.0%} below cumulative WR"
            if drift
            else "rolling WR has not materially decayed versus cumulative proof"
        ),
    }


def bayesian_edge(trades: List[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    alpha_prior = max(0.1, _safe_float(settings.get("PMO_BAYESIAN_ALPHA_PRIOR"), 1.0))
    beta_prior = max(0.1, _safe_float(settings.get("PMO_BAYESIAN_BETA_PRIOR"), 1.0))
    z90 = 1.645
    wins, losses = _wins_losses(row for row in trades if _is_win(row) or _is_loss(row))
    closed = wins + losses
    alpha = alpha_prior + wins
    beta = beta_prior + losses
    total = alpha + beta
    mean = alpha / total if total else 0.0
    variance = (alpha * beta) / ((total * total) * (total + 1.0)) if total > 0 else 0.0
    margin = z90 * sqrt(max(0.0, variance))
    width = min(1.0, margin * 2.0)
    confidence = "LOW" if closed < 20 or width > 0.35 else ("MEDIUM" if closed < 100 or width > 0.18 else "HIGH")
    size_multiplier = 0.35 if confidence == "LOW" else (0.70 if confidence == "MEDIUM" else 1.0)
    return {
        "id": "bayesian_edge",
        "status": "READY" if closed else "DATA_BUILDING",
        "wins": wins,
        "losses": losses,
        "closed": closed,
        "posterior_alpha": round(alpha, 4),
        "posterior_beta": round(beta, 4),
        "posterior_mean_win_rate": round(mean, 4),
        "credible_interval_90": [round(max(0.0, mean - margin), 4), round(min(1.0, mean + margin), 4)],
        "interval_width": round(width, 4),
        "confidence": confidence,
        "position_size_multiplier": size_multiplier,
        "reason": "Bayesian posterior converts point-estimate WR into confidence-aware sizing guidance.",
    }


def counterfactual_analysis(trades: List[Dict[str, Any]], bars_by_symbol: Dict[str, List[Dict[str, Any]]], settings: Dict[str, Any]) -> Dict[str, Any]:
    horizon = int(max(5, _safe_float(settings.get("PMO_COUNTERFACTUAL_HORIZON_MINUTES"), 30)))
    rows: List[Dict[str, Any]] = []
    checked = 0
    data_required = 0
    for trade in trades[-50:]:
        symbol = _symbol(trade)
        exit_time = _row_time(trade)
        exit_price = _safe_float(trade.get("exit_price") or trade.get("close_price") or trade.get("price"), 0)
        bars = bars_by_symbol.get(symbol, []) if isinstance(bars_by_symbol, dict) else []
        if not symbol or not exit_time or exit_price <= 0 or not bars:
            data_required += 1
            continue
        future = []
        for bar in bars:
            ts = _bar_time(bar)
            if ts and exit_time < ts <= exit_time + timedelta(minutes=horizon):
                future.append(bar)
        if not future:
            data_required += 1
            continue
        checked += 1
        highs = [_safe_float(bar.get("high") or bar.get("close"), 0) for bar in future]
        lows = [_safe_float(bar.get("low") or bar.get("close"), 0) for bar in future]
        max_after = max(highs) if highs else exit_price
        min_after = min(lows) if lows else exit_price
        runup = _pct_change(exit_price, max_after)
        drawdown = _pct_change(exit_price, min_after)
        if _is_win(trade) and runup >= _safe_float(settings.get("PMO_COUNTERFACTUAL_MISSED_UPSIDE_PCT"), 3.0):
            lesson = "EXIT_TOO_EARLY"
        elif _is_loss(trade) and drawdown <= -_safe_float(settings.get("PMO_COUNTERFACTUAL_STOP_SAVED_PCT"), 3.0):
            lesson = "STOP_SAVED_MORE"
        else:
            lesson = "EXIT_REASONABLE"
        rows.append({
            "symbol": symbol,
            "exit_time": exit_time.isoformat(),
            "exit_price": round(exit_price, 4),
            "horizon_minutes": horizon,
            "max_after_pct": round(runup, 4),
            "min_after_pct": round(drawdown, 4),
            "lesson": lesson,
        })
    return {
        "id": "counterfactual_reasoning",
        "status": "READY" if checked else "DATA_REQUIRED",
        "checked": checked,
        "data_required": data_required,
        "horizon_minutes": horizon,
        "rows": rows[-12:],
        "reason": "Compares each closed trade exit against the next post-exit price path.",
    }


def causal_inference_proxy(trades: List[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    min_rows = int(max(10, _safe_float(settings.get("PMO_CAUSAL_MIN_ROWS"), 30)))
    rvol_cut = max(0.1, _safe_float(settings.get("PMO_CAUSAL_RVOL_THRESHOLD"), 2.0))
    clean = [row for row in trades if _is_win(row) or _is_loss(row)]
    treated = [row for row in clean if _safe_float(row.get("relative_volume") or row.get("rvol"), 0) >= rvol_cut]
    untreated = [row for row in clean if 0 < _safe_float(row.get("relative_volume") or row.get("rvol"), 0) < rvol_cut]
    if len(clean) < min_rows or len(treated) < 5 or len(untreated) < 5:
        return {
            "id": "causal_inference",
            "status": "DATA_BUILDING",
            "rows": len(clean),
            "treated_rows": len(treated),
            "control_rows": len(untreated),
            "signal_trust_multiplier": 0.5,
            "reason": "needs enough high-RVOL and low-RVOL outcomes before causal proxy can compare intervention-like cohorts",
        }
    tw, tl = _wins_losses(treated)
    uw, ul = _wins_losses(untreated)
    treated_wr = tw / (tw + tl) if (tw + tl) else 0.0
    untreated_wr = uw / (uw + ul) if (uw + ul) else 0.0
    lift = treated_wr - untreated_wr
    status = "CAUSAL_CANDIDATE" if lift >= 0.10 else ("CORRELATED_ONLY" if abs(lift) < 0.05 else "WEAK_CANDIDATE")
    trust_multiplier = 1.1 if status == "CAUSAL_CANDIDATE" else (0.75 if status == "CORRELATED_ONLY" else 0.9)
    return {
        "id": "causal_inference",
        "status": status,
        "rows": len(clean),
        "treatment": f"relative_volume >= {rvol_cut:g}",
        "treated_rows": len(treated),
        "control_rows": len(untreated),
        "treated_win_rate": round(treated_wr, 4),
        "control_win_rate": round(untreated_wr, 4),
        "estimated_lift": round(lift, 4),
        "signal_trust_multiplier": trust_multiplier,
        "reason": "Observational causal proxy; not proof, but it separates likely causal filters from plain correlations.",
    }


def attention_mechanism(bars: List[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    if not bars:
        return {"id": "attention_mechanism", "status": "DATA_REQUIRED", "reason": "bar rows unavailable", "top_bars": [], "signal": "NONE", "score_mod": 0.0}
    max_rows = int(max(5, _safe_float(settings.get("PMO_ATTENTION_LOOKBACK_BARS"), 30)))
    sample = bars[-max_rows:]
    weighted = []
    total = max(1, len(sample) - 1)
    for idx, bar in enumerate(sample):
        recency = idx / total
        rvol = _safe_float(bar.get("relative_volume") or bar.get("rvol"), 1.0)
        spread = abs(_safe_float(bar.get("high"), 0) - _safe_float(bar.get("low"), 0))
        close = max(_safe_float(bar.get("close"), 0), 0.01)
        range_pct = (spread / close) * 100.0
        weight = 1.0 + recency + min(2.0, max(0.0, rvol - 1.0) * 0.6) + min(1.0, range_pct * 0.25)
        weighted.append({
            "timestamp": str(bar.get("timestamp") or bar.get("time") or ""),
            "close": _safe_float(bar.get("close"), 0),
            "relative_volume": rvol,
            "range_pct": round(range_pct, 4),
            "attention_weight": round(weight, 4),
        })
    top = sorted(weighted, key=lambda item: item["attention_weight"], reverse=True)[:5]
    total_weight = sum(item["attention_weight"] for item in weighted) or 1.0
    weighted_close = sum(item["close"] * item["attention_weight"] for item in weighted) / total_weight
    weighted_rvol = sum(item["relative_volume"] * item["attention_weight"] for item in weighted) / total_weight
    first_close = weighted[0]["close"] if weighted else 0.0
    latest_close = weighted[-1]["close"] if weighted else 0.0
    weighted_change_pct = _pct_change(first_close, latest_close)
    if weighted_change_pct >= 0.35 and weighted_rvol >= 1.25:
        signal = "BULLISH_ATTENTION"
        score_mod = min(3.0, weighted_change_pct)
    elif weighted_change_pct <= -0.35 and weighted_rvol >= 1.25:
        signal = "BEARISH_ATTENTION"
        score_mod = -min(3.0, abs(weighted_change_pct))
    else:
        signal = "NEUTRAL_ATTENTION"
        score_mod = 0.0
    return {
        "id": "attention_mechanism",
        "status": "READY",
        "bars": len(sample),
        "top_bars": top,
        "weighted_close": round(weighted_close, 4),
        "weighted_rvol": round(weighted_rvol, 4),
        "weighted_change_pct": round(weighted_change_pct, 4),
        "signal": signal,
        "score_mod": round(score_mod, 4),
        "reason": "Weights recent bars, RVOL spikes, and wide information bars above older neutral bars.",
    }


def adversarial_examples(bars: List[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    if len(bars) < 3:
        return {"id": "adversarial_examples", "status": "DATA_REQUIRED", "reason": "needs at least 3 bars", "patterns": []}
    patterns = []
    rvol_spike = _safe_float(settings.get("PMO_ADVERSARIAL_RVOL_SPIKE"), 3.0)
    for idx in range(1, len(bars) - 1):
        prev_bar, bar, next_bar = bars[idx - 1], bars[idx], bars[idx + 1]
        rvol = _safe_float(bar.get("relative_volume") or bar.get("rvol"), 0)
        next_rvol = _safe_float(next_bar.get("relative_volume") or next_bar.get("rvol"), 0)
        high_break = _safe_float(bar.get("high"), 0) > max(_safe_float(prev_bar.get("high"), 0), _safe_float(next_bar.get("high"), 0))
        close_reversal = _safe_float(next_bar.get("close"), 0) < _safe_float(bar.get("open") or bar.get("close"), 0)
        if rvol >= rvol_spike and (next_rvol <= 1.0 or (high_break and close_reversal)):
            patterns.append({
                "timestamp": str(bar.get("timestamp") or bar.get("time") or ""),
                "pattern": "RVOL_SPIKE_REVERSAL",
                "rvol": rvol,
                "next_rvol": next_rvol,
                "reason": "volume/breakout impulse failed within the next bar",
            })
    return {
        "id": "adversarial_examples",
        "status": "ALERT" if patterns else "CLEAR",
        "patterns": patterns[-8:],
        "reason": "Detects bot-bait style RVOL spikes, false breaks, and immediate reversals.",
    }


def information_asymmetry(candidate: Dict[str, Any], news_rows: List[Dict[str, Any]], earnings_rows: List[Dict[str, Any]], settings: Dict[str, Any], now_value: Any = None) -> Dict[str, Any]:
    rvol = _safe_float(candidate.get("relative_volume") or candidate.get("rvol"), 0)
    move_pct = _safe_float(candidate.get("change_pct") or candidate.get("move_pct"), 0)
    rvol_min = _safe_float(settings.get("PMO_INFO_ASYM_MIN_RVOL"), 3.0)
    move_min = _safe_float(settings.get("PMO_INFO_ASYM_MIN_MOVE_PCT"), 3.0)
    now = _parse_time(now_value) or datetime.now()
    recent_news = []
    for row in news_rows or []:
        ts = _row_time(row)
        if ts and abs((now - ts).total_seconds()) <= _safe_float(settings.get("PMO_INFO_ASYM_NO_NEWS_HOURS"), 4.0) * 3600:
            recent_news.append(row)
    upcoming_earnings = []
    for row in earnings_rows or []:
        ts = _row_time(row)
        if ts and 0 <= (ts - now).days <= int(_safe_float(settings.get("PMO_INFO_ASYM_NO_EARNINGS_DAYS"), 7)):
            upcoming_earnings.append(row)
    detected = bool(rvol >= rvol_min and abs(move_pct) >= move_min and not recent_news and not upcoming_earnings)
    return {
        "id": "information_asymmetry",
        "status": "DETECTED" if detected else "CLEAR",
        "relative_volume": rvol,
        "move_pct": move_pct,
        "recent_news_count": len(recent_news),
        "upcoming_earnings_count": len(upcoming_earnings),
        "direction": "LONG" if move_pct > 0 else ("SHORT" if move_pct < 0 else "NONE"),
        "reason": "large move plus RVOL spike without public catalyst suggests informed order flow" if detected else "no unexplained high-RVOL move detected",
    }


def emergent_behavior(bars: List[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    if len(bars) < 4:
        return {"id": "emergent_behavior", "status": "DATA_REQUIRED", "reason": "needs 4+ bars", "events": []}
    events = []
    for idx in range(1, len(bars) - 2):
        prior_high = max(_safe_float(item.get("high"), 0) for item in bars[max(0, idx - 6):idx])
        bar = bars[idx]
        two_later = bars[idx + 2]
        rvol = _safe_float(bar.get("relative_volume") or bar.get("rvol"), 0)
        broke_out = _safe_float(bar.get("high"), 0) > prior_high and prior_high > 0
        reversed = _safe_float(two_later.get("close"), 0) < prior_high
        if broke_out and rvol >= _safe_float(settings.get("PMO_EMERGENT_CROWD_RVOL"), 3.0) and reversed:
            events.append({
                "timestamp": str(bar.get("timestamp") or bar.get("time") or ""),
                "pattern": "CROWDED_BREAKOUT_FADE",
                "rvol": rvol,
                "prior_high": round(prior_high, 4),
                "close_two_bars_later": _safe_float(two_later.get("close"), 0),
            })
    return {
        "id": "emergent_behavior",
        "status": "CROWDING_DETECTED" if events else "CLEAR",
        "events": events[-8:],
        "reason": "Flags self-defeating crowded signals where massive breakout volume reverses within two bars.",
    }


def meta_learning(trades: List[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    clean = [row for row in trades if _is_win(row) or _is_loss(row)]
    fast_window = int(max(3, _safe_float(settings.get("PMO_META_LEARNING_FAST_WINDOW"), 5)))
    if len(clean) < fast_window:
        return {"id": "meta_learning", "status": "DATA_BUILDING", "rows": len(clean), "adaptation_multiplier": 0.5, "reason": "needs first fast-adaptation window"}
    recent = clean[-fast_window:]
    rw, rl = _wins_losses(recent)
    recent_wr = rw / (rw + rl) if (rw + rl) else 0.0
    all_w, all_l = _wins_losses(clean)
    all_wr = all_w / (all_w + all_l) if (all_w + all_l) else 0.0
    update_pressure = recent_wr - all_wr
    status = "ADAPT_UP" if update_pressure > 0.15 else ("ADAPT_DOWN" if update_pressure < -0.15 else "STABLE")
    adaptation_multiplier = 1.05 if status == "ADAPT_UP" else (0.65 if status == "ADAPT_DOWN" else 1.0)
    return {
        "id": "meta_learning",
        "status": status,
        "rows": len(clean),
        "fast_window": fast_window,
        "recent_win_rate": round(recent_wr, 4),
        "baseline_win_rate": round(all_wr, 4),
        "belief_update_pressure": round(update_pressure, 4),
        "adaptation_multiplier": adaptation_multiplier,
        "reason": "Fast-window gradient proxy for how aggressively PMO should update beliefs in a new regime.",
    }


def counterfactual_exit_policy(counterfactual: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    rows = counterfactual.get("rows") if isinstance(counterfactual.get("rows"), list) else []
    checked = int(_safe_float(counterfactual.get("checked"), 0))
    if not rows or checked <= 0:
        return {
            "status": "DATA_REQUIRED",
            "checked": checked,
            "exit_bias": "UNKNOWN",
            "target_extension_multiplier": 1.0,
            "stop_confidence": "UNKNOWN",
            "reason": "needs post-exit bars before exit policy can be learned",
        }
    exit_early = sum(1 for row in rows if row.get("lesson") == "EXIT_TOO_EARLY")
    stop_saved = sum(1 for row in rows if row.get("lesson") == "STOP_SAVED_MORE")
    reasonable = sum(1 for row in rows if row.get("lesson") == "EXIT_REASONABLE")
    exit_early_rate = exit_early / max(1, len(rows))
    stop_saved_rate = stop_saved / max(1, len(rows))
    if exit_early_rate >= _safe_float(settings.get("PMO_COUNTERFACTUAL_EXIT_EARLY_ALERT_RATE"), 0.35):
        exit_bias = "LET_WINNERS_WORK"
        target_extension = 1.25
    elif stop_saved_rate >= _safe_float(settings.get("PMO_COUNTERFACTUAL_STOP_SAVED_ALERT_RATE"), 0.35):
        exit_bias = "STOPS_ARE_HELPING"
        target_extension = 1.0
    else:
        exit_bias = "EXIT_POLICY_OK"
        target_extension = 1.0
    return {
        "status": "READY",
        "checked": checked,
        "exit_too_early": exit_early,
        "stop_saved_more": stop_saved,
        "exit_reasonable": reasonable,
        "exit_too_early_rate": round(exit_early_rate, 4),
        "stop_saved_rate": round(stop_saved_rate, 4),
        "exit_bias": exit_bias,
        "target_extension_multiplier": target_extension,
        "stop_confidence": "HIGH" if stop_saved_rate >= 0.25 else "NORMAL",
        "reason": "Turns post-exit counterfactual evidence into exit-policy guidance.",
    }


def deep_operational_guidance(signals: Dict[str, Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    counterfactual_policy = counterfactual_exit_policy(signals.get("counterfactual_reasoning", {}), settings)
    concept_size = _safe_float(signals.get("concept_drift", {}).get("position_size_multiplier"), 1.0)
    bayes_size = _safe_float(signals.get("bayesian_edge", {}).get("position_size_multiplier"), 1.0)
    causal_trust = _safe_float(signals.get("causal_inference", {}).get("signal_trust_multiplier"), 1.0)
    meta_size = _safe_float(signals.get("meta_learning", {}).get("adaptation_multiplier"), 1.0)
    attention_mod = _safe_float(signals.get("attention_mechanism", {}).get("score_mod"), 0.0)
    adversarial_size = 0.65 if str(signals.get("adversarial_examples", {}).get("status", "")).upper() == "ALERT" else 1.0
    crowd_size = 0.65 if str(signals.get("emergent_behavior", {}).get("status", "")).upper() == "CROWDING_DETECTED" else 1.0
    info_bonus = 1.05 if str(signals.get("information_asymmetry", {}).get("status", "")).upper() == "DETECTED" else 1.0
    size_multiplier = round(max(0.1, min(concept_size, bayes_size, meta_size, adversarial_size, crowd_size) * min(1.1, causal_trust) * info_bonus), 4)
    score_mod = round(max(-5.0, min(5.0, attention_mod)), 4)
    blockers = []
    if concept_size < 1.0:
        blockers.append("concept_drift")
    if bayes_size < 1.0:
        blockers.append("bayesian_uncertainty")
    if meta_size < 1.0:
        blockers.append("meta_learning_adapt_down")
    if adversarial_size < 1.0:
        blockers.append("adversarial_examples")
    if crowd_size < 1.0:
        blockers.append("crowded_signal")
    return {
        "status": "CAUTION" if blockers else "NORMAL",
        "position_size_multiplier": size_multiplier,
        "score_mod_recommendation": score_mod,
        "score_mod_applied": False,
        "exit_policy": counterfactual_policy,
        "causal_trust_multiplier": causal_trust,
        "bayesian_size_multiplier": bayes_size,
        "meta_adaptation_multiplier": meta_size,
        "attention_signal": signals.get("attention_mechanism", {}).get("signal", "NONE"),
        "blockers": blockers,
        "reason": "Combines the advanced five layers into read-only sizing, scoring, and exit guidance.",
    }


def silence_signal(trades: List[Dict[str, Any]], market_rows: List[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    if not market_rows:
        return {"id": "silence_signal", "status": "DATA_REQUIRED", "reason": "market context rows unavailable", "synthetic_return_pct": 0.0}
    trade_dates = set()
    for row in trades:
        ts = _row_time(row)
        if ts:
            trade_dates.add(ts.date().isoformat())
    silent_rows = []
    synthetic = 0.0
    for row in market_rows:
        ts = _row_time(row) or _parse_time(row.get("date"))
        if not ts:
            continue
        day = ts.date().isoformat()
        if day in trade_dates:
            continue
        regime = str(row.get("regime") or "").upper()
        change_pct = _safe_float(row.get("change_pct") or row.get("market_change_pct"), 0)
        if "DEFENSIVE" in regime or change_pct < 0:
            synthetic += abs(min(0.0, change_pct))
        silent_rows.append({"date": day, "regime": regime or "UNKNOWN", "market_change_pct": change_pct})
    return {
        "id": "silence_signal",
        "status": "READY" if silent_rows else "DATA_BUILDING",
        "silent_periods": len(silent_rows),
        "synthetic_avoided_loss_pct": round(synthetic, 4),
        "sample": silent_rows[-10:],
        "reason": "Credits PMO for deliberate inaction when no-trade periods avoid weak market conditions.",
    }


def analyze_deep_intelligence(
    symbol: str,
    settings: Dict[str, Any],
    *,
    trades: Optional[List[Dict[str, Any]]] = None,
    bars: Optional[List[Dict[str, Any]]] = None,
    bars_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    candidate: Optional[Dict[str, Any]] = None,
    news_rows: Optional[List[Dict[str, Any]]] = None,
    earnings_rows: Optional[List[Dict[str, Any]]] = None,
    market_rows: Optional[List[Dict[str, Any]]] = None,
    now_value: Any = None,
) -> Dict[str, Any]:
    trades = trades or []
    bars = bars or []
    bars_by_symbol = bars_by_symbol or ({str(symbol or "").upper(): bars} if bars else {})
    candidate = candidate or {}
    news_rows = news_rows or []
    earnings_rows = earnings_rows or []
    market_rows = market_rows or []
    signals = {
        "counterfactual_reasoning": counterfactual_analysis(trades, bars_by_symbol, settings),
        "concept_drift": concept_drift_monitor(trades, settings),
        "causal_inference": causal_inference_proxy(trades, settings),
        "bayesian_edge": bayesian_edge(trades, settings),
        "attention_mechanism": attention_mechanism(bars, settings),
        "adversarial_examples": adversarial_examples(bars, settings),
        "meta_learning": meta_learning(trades, settings),
        "information_asymmetry": information_asymmetry(candidate, news_rows, earnings_rows, settings, now_value=now_value),
        "emergent_behavior": emergent_behavior(bars, settings),
        "silence_signal": silence_signal(trades, market_rows, settings),
    }
    operational = deep_operational_guidance(signals, settings)
    alert_keys = [key for key, value in signals.items() if str(value.get("status", "")).upper() in {"ALERT", "BLOCK", "DETECTED", "CROWDING_DETECTED", "ADAPT_DOWN"}]
    ready_count = sum(1 for value in signals.values() if str(value.get("status", "")).upper() in {"READY", "CLEAR", "DETECTED", "ALERT", "CAUSAL_CANDIDATE", "WEAK_CANDIDATE", "CORRELATED_ONLY", "STABLE", "ADAPT_UP", "ADAPT_DOWN", "CROWDING_DETECTED"})
    recommended_size = _safe_float(operational.get("position_size_multiplier"), 1.0)
    if alert_keys:
        status = "ATTENTION_REQUIRED"
    elif ready_count >= 5:
        status = "READY"
    else:
        status = "DATA_BUILDING"
    return {
        "ok": True,
        "enabled": bool(settings.get("ENABLE_PMO_DEEP_INTELLIGENCE", True)),
        "symbol": str(symbol or "").upper(),
        "status": status,
        "mode": "READ_ONLY_DEEP_INTELLIGENCE",
        "read_only": True,
        "score_influence": bool(settings.get("PMO_DEEP_INTELLIGENCE_SCORE_INFLUENCE", False)),
        "orders_placed": False,
        "live_unlocked": False,
        "settings_changed": False,
        "ready_count": ready_count,
        "alert_keys": alert_keys,
        "recommended_position_size_multiplier": recommended_size,
        "operational_guidance": operational,
        "signals": signals,
        "journal": {
            "deep_status": status,
            "deep_ready_count": ready_count,
            "deep_alerts": ",".join(alert_keys),
            "deep_size_mult": recommended_size,
            "deep_score_mod_rec": operational.get("score_mod_recommendation", 0),
            "deep_attention_signal": operational.get("attention_signal", "NONE"),
            "deep_exit_policy": (operational.get("exit_policy") or {}).get("exit_bias", "UNKNOWN"),
            "concept_drift": signals["concept_drift"].get("status"),
            "bayesian_confidence": signals["bayesian_edge"].get("confidence"),
            "causal_trust_mult": operational.get("causal_trust_multiplier", 1.0),
            "meta_adaptation_mult": operational.get("meta_adaptation_multiplier", 1.0),
            "info_asymmetry": signals["information_asymmetry"].get("status"),
            "silence_avoided_loss_pct": signals["silence_signal"].get("synthetic_avoided_loss_pct", 0),
        },
    }
