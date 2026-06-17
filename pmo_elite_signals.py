"""
PMO elite signal layer.

Read-only research adapters for:
- options flow confirmation
- social velocity acceleration
- USD/JPY carry unwind caution
- ensemble voting across PMO engines
- walk-forward validation

This module never places orders, unlocks live trading, or mutates settings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
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


def _side(value: Any) -> str:
    text = _text(value)
    if any(token in text for token in ("PUT", "BEAR", "SELL", "SHORT", "DOWN", "NEGATIVE", "RISK_OFF", "UNWIND")):
        return "BEAR"
    if any(token in text for token in ("CALL", "BULL", "BUY", "LONG", "UP", "POSITIVE", "ACCELERATION", "CONFIRM")):
        return "BULL"
    return "NEUTRAL"


def _symbol(row: Dict[str, Any]) -> str:
    return _text(row.get("symbol") or row.get("ticker") or row.get("underlying"))


def vote(engine: str, signal: str, side: str, weight: float, confidence: float, note: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    side_clean = side if side in {"BULL", "BEAR", "NEUTRAL"} else _side(side)
    weight_clean = max(0.0, min(5.0, _float(weight, 1.0)))
    confidence_clean = max(0.0, min(1.0, _float(confidence, 0.0)))
    return {
        "engine": engine,
        "signal": signal,
        "side": side_clean,
        "weight": round(weight_clean, 4),
        "confidence": round(confidence_clean, 4),
        "score": round(weight_clean * confidence_clean, 4),
        "note": note,
        "data": data or {},
    }


def disabled_vote(engine: str, note: str) -> Dict[str, Any]:
    return vote(engine, "DISABLED", "NEUTRAL", 0.0, 0.0, note)


def analyze_options_flow(symbol: str, events: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(settings.get("ENABLE_PMO_OPTIONS_FLOW_SIGNAL", True)):
        return {"ok": True, "enabled": False, "vote": disabled_vote("options_flow", "options flow signal disabled"), "events": []}
    clean_symbol = _text(symbol)
    lookback = _float(settings.get("PMO_OPTIONS_FLOW_LOOKBACK_MINUTES"), 30)
    min_contracts = _int(settings.get("PMO_OPTIONS_FLOW_MIN_CONTRACTS"), 1000)
    min_premium = _float(settings.get("PMO_OPTIONS_FLOW_MIN_PREMIUM_USD"), 100000)
    max_dte = _int(settings.get("PMO_OPTIONS_FLOW_MAX_DTE"), 7)
    matching: List[Dict[str, Any]] = []
    for raw in events or []:
        if not isinstance(raw, dict) or _symbol(raw) != clean_symbol:
            continue
        minutes_ago = _float(raw.get("minutes_ago") or raw.get("age_minutes"), 9999)
        contracts = _int(raw.get("contracts") or raw.get("size") or raw.get("volume"), 0)
        premium = _float(raw.get("premium") or raw.get("premium_usd") or raw.get("total_premium"), 0)
        dte = _int(raw.get("dte") or raw.get("days_to_expiration") or raw.get("expiry_days"), 999)
        if minutes_ago <= lookback and contracts >= min_contracts and premium >= min_premium and dte <= max_dte:
            row = dict(raw)
            row["_contracts"] = contracts
            row["_premium"] = premium
            row["_dte"] = dte
            row["_side"] = _side(raw.get("side") or raw.get("option_type") or raw.get("type"))
            matching.append(row)
    bull_premium = sum(_float(row.get("_premium"), 0) for row in matching if row.get("_side") == "BULL")
    bear_premium = sum(_float(row.get("_premium"), 0) for row in matching if row.get("_side") == "BEAR")
    side = "BULL" if bull_premium > bear_premium and bull_premium > 0 else "BEAR" if bear_premium > bull_premium and bear_premium > 0 else "NEUTRAL"
    total_premium = bull_premium + bear_premium
    confidence = min(1.0, total_premium / max(min_premium * 5, 1))
    signal = "UNUSUAL_CALL_FLOW" if side == "BULL" else "UNUSUAL_PUT_FLOW" if side == "BEAR" else "NO_UNUSUAL_FLOW"
    note = f"{len(matching)} unusual option flow event(s); call ${bull_premium:,.0f}, put ${bear_premium:,.0f}"
    return {
        "ok": True,
        "enabled": True,
        "symbol": clean_symbol,
        "vote": vote("options_flow", signal, side, settings.get("PMO_OPTIONS_FLOW_VOTE_WEIGHT", 1.4), confidence, note, {"events": len(matching), "call_premium": bull_premium, "put_premium": bear_premium}),
        "events": matching[:20],
    }


def analyze_social_velocity(symbol: str, samples: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(settings.get("ENABLE_PMO_SOCIAL_VELOCITY_SIGNAL", True)):
        return {"ok": True, "enabled": False, "vote": disabled_vote("social_velocity", "social velocity signal disabled"), "samples": []}
    clean_symbol = _text(symbol)
    min_ratio = _float(settings.get("PMO_SOCIAL_VELOCITY_MIN_RATIO"), 5.0)
    min_mentions = _int(settings.get("PMO_SOCIAL_VELOCITY_MIN_MENTIONS"), 25)
    matching = [dict(row) for row in samples or [] if isinstance(row, dict) and _symbol(row) == clean_symbol]
    current = 0.0
    baseline = 0.0
    if matching:
        current = sum(_float(row.get("mentions") or row.get("current_mentions") or row.get("count"), 0) for row in matching)
        baseline_values = [_float(row.get("baseline_mentions") or row.get("baseline") or row.get("avg_mentions"), 0) for row in matching]
        baseline = sum(baseline_values) / len(baseline_values) if baseline_values else 0.0
    ratio = current / max(1.0, baseline)
    active = current >= min_mentions and ratio >= min_ratio
    confidence = min(1.0, ratio / max(min_ratio * 2, 1))
    signal = "SOCIAL_ACCELERATION" if active else "SOCIAL_NORMAL"
    side = "BULL" if active else "NEUTRAL"
    note = f"mentions {current:.0f}, baseline {baseline:.1f}, velocity {ratio:.2f}x"
    return {
        "ok": True,
        "enabled": True,
        "symbol": clean_symbol,
        "vote": vote("social_velocity", signal, side, settings.get("PMO_SOCIAL_VELOCITY_VOTE_WEIGHT", 0.8), confidence if active else 0.0, note, {"mentions": current, "baseline": baseline, "ratio": ratio}),
        "samples": matching[:20],
    }


def analyze_usdjpy_carry(bars: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(settings.get("ENABLE_PMO_USDJPY_CARRY_SIGNAL", True)):
        return {"ok": True, "enabled": False, "vote": disabled_vote("usdjpy_carry", "USD/JPY carry signal disabled")}
    rows = [row for row in bars or [] if isinstance(row, dict)]
    threshold = abs(_float(settings.get("PMO_USDJPY_CARRY_DROP_5M_PCT"), 0.3))
    if len(rows) < 2:
        return {"ok": True, "enabled": True, "status": "DATA_REQUIRED", "vote": vote("usdjpy_carry", "DATA_REQUIRED", "NEUTRAL", 0.0, 0.0, "USD/JPY bars unavailable")}
    start = _float(rows[0].get("close") or rows[0].get("c"), 0)
    end = _float(rows[-1].get("close") or rows[-1].get("c"), 0)
    change_pct = ((end - start) / start * 100.0) if start > 0 else 0.0
    if change_pct <= -threshold:
        signal = "CARRY_UNWIND_RISK"
        side = "BEAR"
        confidence = min(1.0, abs(change_pct) / max(threshold * 2, 0.01))
    else:
        signal = "CARRY_STABLE"
        side = "NEUTRAL"
        confidence = 0.0
    note = f"USD/JPY 5m change {change_pct:+.3f}% vs caution threshold -{threshold:.3f}%"
    return {
        "ok": True,
        "enabled": True,
        "status": "READY",
        "vote": vote("usdjpy_carry", signal, side, settings.get("PMO_USDJPY_CARRY_VOTE_WEIGHT", 1.2), confidence, note, {"change_pct": round(change_pct, 4), "threshold": threshold}),
    }


def ensemble_vote(votes: Iterable[Dict[str, Any]], settings: Dict[str, Any]) -> Dict[str, Any]:
    if not bool(settings.get("ENABLE_PMO_ENSEMBLE_VOTING", True)):
        return {"enabled": False, "status": "DISABLED", "votes": [], "blockers": []}
    usable = [dict(row) for row in votes or [] if isinstance(row, dict)]
    bull_score = sum(_float(row.get("score"), 0) for row in usable if row.get("side") == "BULL")
    bear_score = sum(_float(row.get("score"), 0) for row in usable if row.get("side") == "BEAR")
    bull_votes = sum(1 for row in usable if row.get("side") == "BULL" and _float(row.get("confidence"), 0) > 0)
    bear_votes = sum(1 for row in usable if row.get("side") == "BEAR" and _float(row.get("confidence"), 0) > 0)
    directional = bull_votes + bear_votes
    min_bull_votes = _int(settings.get("PMO_ENSEMBLE_MIN_BULL_VOTES"), 6)
    min_agree = _float(settings.get("PMO_ENSEMBLE_MIN_AGREE_RATIO"), 0.6)
    agree_ratio = bull_votes / directional if directional else 0.0
    conflict = bear_score >= bull_score and bear_votes > 0
    ready = bull_votes >= min_bull_votes and agree_ratio >= min_agree and not conflict
    status = "BULLISH_ENSEMBLE" if ready else "CONFLICT" if conflict else "BUILDING"
    blockers = []
    if not ready:
        blockers.append(f"ensemble needs {min_bull_votes}+ bullish votes and {min_agree:.0%}+ agreement; got {bull_votes} bull, {bear_votes} bear, {agree_ratio:.0%}")
    return {
        "enabled": True,
        "status": status,
        "ready": ready,
        "bull_votes": bull_votes,
        "bear_votes": bear_votes,
        "neutral_votes": sum(1 for row in usable if row.get("side") == "NEUTRAL"),
        "bull_score": round(bull_score, 4),
        "bear_score": round(bear_score, 4),
        "agree_ratio": round(agree_ratio, 4),
        "min_bull_votes": min_bull_votes,
        "min_agree_ratio": min_agree,
        "blockers": blockers,
        "votes": usable,
        "live_unlocked": False,
        "orders_placed": False,
    }


def _row_outcome(row: Dict[str, Any]) -> Optional[bool]:
    status = _text(row.get("status") or row.get("result") or row.get("outcome"))
    pnl = _float(row.get("pnl") or row.get("pnl_usd") or row.get("profit_loss") or row.get("realized_pnl"), 0.0)
    if "WIN" in status or pnl > 0:
        return True
    if "LOSS" in status or pnl < 0:
        return False
    return None


def walk_forward_validation(rows: Iterable[Dict[str, Any]], settings: Dict[str, Any], signal_fields: Optional[List[str]] = None) -> Dict[str, Any]:
    if not bool(settings.get("ENABLE_PMO_WALK_FORWARD_VALIDATION", True)):
        return {"enabled": False, "status": "DISABLED", "validations": []}
    closed = [dict(row) for row in rows or [] if isinstance(row, dict) and _row_outcome(row) is not None]
    closed.sort(key=lambda row: str(row.get("timestamp") or row.get("entry_timestamp") or row.get("closed_at") or ""))
    min_train = _int(settings.get("PMO_WALK_FORWARD_MIN_TRAIN_ROWS"), 40)
    min_test = _int(settings.get("PMO_WALK_FORWARD_MIN_TEST_ROWS"), 10)
    split = min(max(min_train, len(closed) - min_test), len(closed))
    train = closed[:split]
    test = closed[split:]
    fields = signal_fields or ["edge_signal", "intel_signal", "confluence_status", "gap_signal", "orb_signal", "pattern_direction"]
    validations: List[Dict[str, Any]] = []
    for field in fields:
        train_values = {_text(row.get(field)) for row in train if _text(row.get(field))}
        test_rows = [row for row in test if _text(row.get(field)) in train_values and _text(row.get(field))]
        wins = sum(1 for row in test_rows if _row_outcome(row) is True)
        losses = sum(1 for row in test_rows if _row_outcome(row) is False)
        total = wins + losses
        wr = wins / total if total else 0.0
        validations.append({
            "field": field,
            "train_values": sorted(train_values),
            "test_rows": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wr, 4),
            "validated": total >= min_test and wr >= _float(settings.get("PMO_WALK_FORWARD_MIN_TEST_WIN_RATE"), 0.52),
        })
    validated_count = sum(1 for row in validations if row.get("validated"))
    return {
        "enabled": True,
        "status": "READY" if len(test) >= min_test else "BUILDING",
        "rows": len(closed),
        "train_rows": len(train),
        "test_rows": len(test),
        "minimum_train_rows": min_train,
        "minimum_test_rows": min_test,
        "validated_signals": validated_count,
        "validations": validations,
        "note": "Walk-forward uses chronological train rows, then tests only on later unseen rows.",
    }


def build_votes_from_candidate(candidate: Dict[str, Any], settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks = [
        ("pattern", candidate.get("pattern_direction") or (candidate.get("pattern") or {}).get("pattern_direction"), settings.get("PMO_ENSEMBLE_PATTERN_WEIGHT", 1.0)),
        ("fvg", candidate.get("fvg_signal") or (candidate.get("fvg") or {}).get("fvg_signal"), settings.get("PMO_ENSEMBLE_FVG_WEIGHT", 1.0)),
        ("edge", candidate.get("edge_signal") or (candidate.get("edge_engines") or {}).get("edge_signal"), settings.get("PMO_ENSEMBLE_EDGE_WEIGHT", 1.2)),
        ("intelligence", candidate.get("intel_signal") or (candidate.get("intelligence_bundle") or {}).get("signal"), settings.get("PMO_ENSEMBLE_INTEL_WEIGHT", 1.0)),
        ("ml", candidate.get("ml_signal") or (candidate.get("ml") or {}).get("signal"), settings.get("PMO_ENSEMBLE_ML_WEIGHT", 0.8)),
        ("vwap", candidate.get("vwap_score_status") or candidate.get("vwap_status"), settings.get("PMO_ENSEMBLE_VWAP_WEIGHT", 0.8)),
        ("rvol", "PASS" if _float(candidate.get("relative_volume") or candidate.get("rvol"), 0) >= _float(settings.get("PMO_WHY_NOT_MIN_RVOL", 1.5), 1.5) else "LOW", settings.get("PMO_ENSEMBLE_RVOL_WEIGHT", 1.0)),
    ]
    votes = []
    for name, raw, weight in checks:
        side = _side(raw)
        confidence = 0.8 if side in {"BULL", "BEAR"} else 0.0
        votes.append(vote(name, str(raw or "NEUTRAL"), side, _float(weight, 1.0), confidence, f"{name} signal {raw or 'NEUTRAL'}"))
    elite = candidate.get("elite_signals")
    if isinstance(elite, dict):
        for item in elite.get("votes", []) or []:
            if isinstance(item, dict):
                votes.append(item)
    return votes
