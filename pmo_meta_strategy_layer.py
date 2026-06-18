from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ACTIONS = ("TAKE_FULL", "TAKE_HALF", "WAIT_CONFIRMATION", "SKIP")


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace("%", "").strip())
    except Exception:
        return default


def _ts(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return datetime.min


def _read_csv(path: Path, limit: int = 5000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as handle:
            return list(csv.DictReader(handle))[-limit:]
    except Exception:
        return []


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def _score_bucket(score: float) -> str:
    if score < 40:
        return "LT40"
    if score < 55:
        return "40_54"
    if score < 65:
        return "55_64"
    if score < 75:
        return "65_74"
    if score < 78:
        return "75_77"
    if score < 93:
        return "78_92"
    return "93_PLUS"


def _rvol_bucket(rvol: float) -> str:
    if rvol <= 0:
        return "RVOL_UNKNOWN"
    if rvol < 1.0:
        return "RVOL_LOW"
    if rvol < 2.0:
        return "RVOL_OK"
    if rvol < 4.0:
        return "RVOL_HIGH"
    return "RVOL_EXTREME"


def _time_bucket(dt: datetime) -> str:
    if dt == datetime.min:
        return "TIME_UNKNOWN"
    minute = dt.hour * 60 + dt.minute
    if 570 <= minute < 585:
        return "09:30_09:44"
    if 585 <= minute < 630:
        return "09:45_10:29"
    if 630 <= minute < 720:
        return "10:30_11:59"
    if 720 <= minute < 900:
        return "MIDDAY"
    if 900 <= minute < 930:
        return "15:00_15:29"
    if minute >= 930:
        return "15:30_PLUS"
    return "OFF_HOURS"


def _normalize_trade(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
    if not symbol or symbol == "SYSTEM":
        return None
    status = str(row.get("status") or row.get("result") or row.get("outcome") or "").upper()
    pnl = _f(row.get("pnl") or row.get("pnl_usd") or row.get("realized_pnl"), 0)
    closed = status.startswith("CLOSED") or status in {"WIN", "LOSS", "COMPLETE", "COMPLETED"} or pnl != 0
    if not closed:
        return None
    score = _f(row.get("score") or row.get("pmo_score"), 0)
    rvol = _f(row.get("relative_volume") or row.get("rvol"), 0)
    dt = _ts(row.get("entry_timestamp") or row.get("timestamp") or row.get("time"))
    confidence = _f(row.get("ml_win_prob") or row.get("confidence") or row.get("score"), 0)
    if confidence > 1:
        confidence = confidence / 100.0
    confidence = max(0.0, min(1.0, confidence))
    return {
        "timestamp": row.get("timestamp") or row.get("entry_timestamp") or "",
        "dt": dt,
        "symbol": symbol,
        "status": status,
        "side": str(row.get("side") or "LONG").upper(),
        "score": score,
        "score_bucket": _score_bucket(score),
        "pnl": pnl,
        "win": 1 if pnl > 0 or "WIN" in status else 0,
        "regime": str(row.get("market_regime") or row.get("regime") or "UNKNOWN").upper() or "UNKNOWN",
        "rvol": rvol,
        "rvol_bucket": _rvol_bucket(rvol),
        "time_bucket": _time_bucket(dt),
        "vwap_distance": _f(row.get("vwap_distance_pct") or row.get("vwap_distance") or row.get("entry_distance_vwap"), 0),
        "gap_signal": str(row.get("gap_signal") or "").upper(),
        "orb_signal": str(row.get("orb_signal") or "").upper(),
        "ml_confidence": confidence,
        "deep_size_mult": _f(row.get("deep_size_mult"), 1.0),
    }


def _state_key(row: Dict[str, Any]) -> str:
    regime = str(row.get("regime") or "UNKNOWN").upper()
    if "BULL" in regime:
        regime = "BULL"
    elif "BEAR" in regime:
        regime = "BEAR"
    elif "DEFENSIVE" in regime:
        regime = "DEFENSIVE"
    elif "MIXED" in regime:
        regime = "MIXED"
    return "|".join([regime, str(row.get("score_bucket")), str(row.get("rvol_bucket")), str(row.get("time_bucket"))])


def _taken_action(row: Dict[str, Any]) -> str:
    size_mult = _f(row.get("deep_size_mult"), 1.0)
    if size_mult and size_mult <= 0.55:
        return "TAKE_HALF"
    if row.get("score", 0) < 55:
        return "WAIT_CONFIRMATION"
    return "TAKE_FULL"


def _counterfactual_utilities(row: Dict[str, Any]) -> Dict[str, float]:
    pnl = _f(row.get("pnl"), 0)
    win = pnl > 0
    return {
        "TAKE_FULL": pnl,
        "TAKE_HALF": pnl * 0.5,
        "WAIT_CONFIRMATION": pnl * (0.68 if win else 0.42),
        "SKIP": 0.0,
    }


def _regret_table(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    states: Dict[str, Dict[str, Any]] = {}
    events: List[Dict[str, Any]] = []
    for row in rows:
        state = _state_key(row)
        action = _taken_action(row)
        utilities = _counterfactual_utilities(row)
        chosen = utilities[action]
        bucket = states.setdefault(state, {"state": state, "samples": 0, "taken": {a: 0 for a in ACTIONS}, "regret": {a: 0.0 for a in ACTIONS}, "utility": {a: 0.0 for a in ACTIONS}})
        bucket["samples"] += 1
        bucket["taken"][action] += 1
        for alt in ACTIONS:
            regret = utilities[alt] - chosen
            bucket["regret"][alt] += regret
            bucket["utility"][alt] += utilities[alt]
        events.append({
            "timestamp": row.get("timestamp"),
            "symbol": row.get("symbol"),
            "state": state,
            "taken_action": action,
            "pnl": round(_f(row.get("pnl"), 0), 4),
            "best_counterfactual": max(utilities, key=utilities.get),
            "regret": {key: round(value - chosen, 4) for key, value in utilities.items()},
        })
    ranked = sorted(states.values(), key=lambda item: item["samples"], reverse=True)
    for item in ranked:
        item["regret"] = {key: round(value, 4) for key, value in item["regret"].items()}
        item["utility"] = {key: round(value, 4) for key, value in item["utility"].items()}
        item["strategy"] = _regret_matching(item["regret"])
    return {"states": ranked, "events": events[-250:]}


def _regret_matching(regrets: Dict[str, float]) -> Dict[str, float]:
    positive = {action: max(0.0, _f(regrets.get(action), 0)) for action in ACTIONS}
    total = sum(positive.values())
    if total <= 0:
        return {"TAKE_FULL": 0.25, "TAKE_HALF": 0.25, "WAIT_CONFIRMATION": 0.25, "SKIP": 0.25}
    return {action: round(positive[action] / total, 4) for action in ACTIONS}


def _current_strategy(rows: List[Dict[str, Any]], regret: Dict[str, Any], current_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    current_state = current_state or {}
    probe = {
        "regime": current_state.get("regime") or (rows[-1].get("regime") if rows else "UNKNOWN"),
        "score_bucket": _score_bucket(_f(current_state.get("score"), rows[-1].get("score", 0) if rows else 0)),
        "rvol_bucket": _rvol_bucket(_f(current_state.get("rvol"), rows[-1].get("rvol", 0) if rows else 0)),
        "time_bucket": current_state.get("time_bucket") or (rows[-1].get("time_bucket") if rows else "TIME_UNKNOWN"),
    }
    state = _state_key(probe)
    exact = next((item for item in regret.get("states", []) if item.get("state") == state), None)
    if exact:
        distribution = exact.get("strategy", {})
        source = "EXACT_STATE_REGRET"
        samples = exact.get("samples", 0)
    else:
        distribution = _portfolio_default_strategy(rows, current_state)
        source = "PORTFOLIO_DEFAULT_UNTIL_STATE_HAS_SAMPLES"
        samples = 0
    confidence = "LOW"
    if len(rows) >= 500 and samples >= 25:
        confidence = "HIGH"
    elif len(rows) >= 200 and samples >= 10:
        confidence = "MEDIUM"
    action = max(distribution, key=distribution.get) if distribution else "WAIT_CONFIRMATION"
    return {
        "status": "READY_READ_ONLY" if rows else "DATA_BUILDING",
        "state": state,
        "sample_count": samples,
        "total_closed_trades": len(rows),
        "strategy_source": source,
        "action_distribution": distribution,
        "recommended_action": action,
        "confidence": confidence,
        "readiness_note": "CFR recommendations are read-only until 500+ closed decisions and owner review.",
    }


def _portfolio_default_strategy(rows: List[Dict[str, Any]], current_state: Dict[str, Any]) -> Dict[str, float]:
    recent = rows[-50:] if rows else []
    wr = sum(row["win"] for row in recent) / max(1, len(recent))
    pnl_today = _f(current_state.get("pnl_today"), 0)
    trades_today = int(_f(current_state.get("trades_today"), 0))
    risk_penalty = 0.0
    if pnl_today < 0:
        risk_penalty += 0.12
    if trades_today >= 10:
        risk_penalty += 0.12
    take = max(0.05, min(0.45, wr * 0.45 - risk_penalty))
    half = max(0.15, min(0.40, wr * 0.35 + 0.08))
    wait = max(0.20, min(0.50, 0.35 + risk_penalty))
    skip = max(0.05, 1.0 - take - half - wait)
    total = take + half + wait + skip
    return {
        "TAKE_FULL": round(take / total, 4),
        "TAKE_HALF": round(half / total, 4),
        "WAIT_CONFIRMATION": round(wait / total, 4),
        "SKIP": round(skip / total, 4),
    }


def _attention_layer(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    weighted = []
    for row in rows[-200:]:
        price_proxy = abs(_f(row.get("vwap_distance"), 0)) + abs(_f(row.get("pnl"), 0)) / 10.0
        weight = max(0.01, _f(row.get("rvol"), 0)) * max(1.0, price_proxy) * max(0.4, _f(row.get("score"), 0) / 70.0)
        weighted.append({"symbol": row.get("symbol"), "state": _state_key(row), "attention_weight": round(weight, 4), "pnl": row.get("pnl")})
    top = sorted(weighted, key=lambda item: item["attention_weight"], reverse=True)[:10]
    return {
        "status": "READY" if len(rows) >= 20 else "DATA_BUILDING",
        "method": "rvol * information_change * score_pressure",
        "samples": len(weighted),
        "top_attention_events": top,
    }


def _adversarial_model(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    traps = [row for row in rows if row["rvol"] >= 2.0 and row["pnl"] < 0]
    high_score_losses = [row for row in rows if row["score"] >= 75 and row["pnl"] < 0]
    return {
        "status": "READY" if len(rows) >= 50 else "DATA_BUILDING",
        "framing": "Market modeled as opponent: avoid being exit liquidity.",
        "high_rvol_loss_count": len(traps),
        "high_score_loss_count": len(high_score_losses),
        "trap_rate": round(len(traps) / max(1, len([row for row in rows if row["rvol"] >= 2.0])), 4),
        "current_guardrail": "Treat high RVOL as participation, not direction; require alignment with gap/ORB/order-flow.",
    }


def _alpha_decay(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(str(row.get("time_bucket")), []).append(row)
    summary = []
    for bucket, items in buckets.items():
        wins = sum(item["win"] for item in items)
        summary.append({"time_bucket": bucket, "n": len(items), "win_rate": round(wins / max(1, len(items)), 4), "avg_pnl": round(sum(item["pnl"] for item in items) / max(1, len(items)), 4)})
    summary.sort(key=lambda item: item["avg_pnl"], reverse=True)
    return {
        "status": "READY" if len(rows) >= 50 else "DATA_BUILDING",
        "lead_time_question": "What does PMO know before average participants price it in?",
        "time_decay_edges": summary,
        "first_signal_priority": "order_flow_imbalance_then_attention_then_confirmation",
    }


def _model_router(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    states: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        state = str(row.get("regime") or "UNKNOWN")
        states.setdefault(state, []).append(row)
    models = {}
    for state, items in states.items():
        wr = sum(item["win"] for item in items) / max(1, len(items))
        models[state] = {
            "samples": len(items),
            "win_rate": round(wr, 4),
            "status": "ROUTE_READY" if len(items) >= 20 else "COLLECT_MORE",
            "model": f"model_{state.lower()}",
        }
    return {
        "status": "READY" if models else "DATA_BUILDING",
        "active_routing": "regime_state_model_family",
        "models": models,
        "note": "Routes recommendations by regime; does not replace executor gates.",
    }


def _shadow_tracker(why_not: Dict[str, Any], why_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = why_not.get("rows", []) if isinstance(why_not.get("rows"), list) else []
    candidates = [row for row in rows if _f(row.get("score"), 0) >= 40]
    blocked = [row for row in candidates if str(row.get("severity", "")).upper() == "BLOCKED"]
    event_candidates = [row for row in why_events if _f(row.get("score"), 0) >= 40]
    return {
        "status": "DATA_BUILDING",
        "shadow_candidates_visible": len(candidates),
        "blocked_now": len(blocked),
        "historical_shadow_events": len(event_candidates),
        "tracked_fields": ["symbol", "score", "severity", "blockers", "next_action", "future_price_outcome_pending"],
        "next_step": "Attach forward return snapshots to blocked candidates so shadow P&L can be compared with real P&L.",
    }


def _confidence_calibration(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    buckets = {"0_50": [], "50_60": [], "60_70": [], "70_80": [], "80_100": []}
    for row in rows:
        conf = _f(row.get("ml_confidence"), 0)
        key = "0_50" if conf < 0.5 else "50_60" if conf < 0.6 else "60_70" if conf < 0.7 else "70_80" if conf < 0.8 else "80_100"
        buckets[key].append(row)
    out = {}
    errors = []
    for key, items in buckets.items():
        if not items:
            out[key] = {"n": 0, "win_rate": 0, "calibration_error": None}
            continue
        avg_conf = sum(_f(item.get("ml_confidence"), 0) for item in items) / len(items)
        wr = sum(item["win"] for item in items) / len(items)
        err = abs(avg_conf - wr)
        errors.append(err)
        out[key] = {"n": len(items), "avg_confidence": round(avg_conf, 4), "win_rate": round(wr, 4), "calibration_error": round(err, 4)}
    return {
        "status": "READY" if len(rows) >= 50 else "DATA_BUILDING",
        "buckets": out,
        "mean_calibration_error": round(sum(errors) / max(1, len(errors)), 4),
        "sizing_rule": "Discount size when confidence bucket is overconfident versus realized win rate.",
    }


def _prediction_error_model(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    recent = rows[-25:]
    prior = rows[:-25]
    recent_wr = sum(row["win"] for row in recent) / max(1, len(recent))
    prior_wr = sum(row["win"] for row in prior) / max(1, len(prior))
    drift = recent_wr - prior_wr
    return {
        "status": "READY" if len(rows) >= 50 else "DATA_BUILDING",
        "recent_win_rate": round(recent_wr, 4),
        "prior_win_rate": round(prior_wr, 4),
        "prediction_error_drift": round(drift, 4),
        "trust_state": "DEGRADE_MODEL_TRUST" if drift < -0.12 else "EXPAND_MODEL_TRUST" if drift > 0.12 else "STABLE",
        "core_question": "Is PMO more right in this situation than usual?",
    }


def analyze_meta_strategy_layer(
    trade_journal_path: Path,
    why_not_path: Optional[Path] = None,
    why_not_events_path: Optional[Path] = None,
    settings: Optional[Dict[str, Any]] = None,
    current_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    settings = settings or {}
    rows = [item for item in (_normalize_trade(row) for row in _read_csv(trade_journal_path, int(_f(settings.get("PMO_META_MAX_ROWS"), 5000)))) if item is not None]
    rows.sort(key=lambda item: item.get("dt") or datetime.min)
    regret = _regret_table(rows)
    why_not = _read_json(why_not_path) if why_not_path else {}
    why_events = _read_csv(why_not_events_path, int(_f(settings.get("PMO_META_SHADOW_EVENT_ROWS"), 5000))) if why_not_events_path else []
    modules = {
        "counterfactual_regret_minimization": _current_strategy(rows, regret, current_state),
        "regret_table": {"status": "READY" if rows else "DATA_BUILDING", "state_count": len(regret.get("states", [])), "event_count": len(regret.get("events", [])), "top_states": regret.get("states", [])[:12]},
        "adversarial_market_model": _adversarial_model(rows),
        "attention_weighting": _attention_layer(rows),
        "alpha_decay_lead_time": _alpha_decay(rows),
        "regime_model_router": _model_router(rows),
        "shadow_trade_tracker": _shadow_tracker(why_not, why_events),
        "confidence_calibration": _confidence_calibration(rows),
        "prediction_error_model": _prediction_error_model(rows),
    }
    blockers = []
    if len(rows) < 200:
        blockers.append(f"only {len(rows)} closed trades; CFR is data-building until 200+ and strongest at 500+")
    if modules["shadow_trade_tracker"]["historical_shadow_events"] == 0:
        blockers.append("shadow trade outcomes not yet attached to blocked candidates")
    return {
        "ok": True,
        "engine": "PMO_META_STRATEGY_LAYER",
        "status": "READY_READ_ONLY" if rows else "DATA_BUILDING",
        "read_only": True,
        "orders_placed": False,
        "settings_changed": False,
        "live_trading_changed": False,
        "closed_trades": len(rows),
        "module_count": len(modules),
        "blockers": blockers,
        "modules": modules,
        "journal": {
            "meta_status": "READY_READ_ONLY" if rows else "DATA_BUILDING",
            "meta_closed_trades": len(rows),
            "cfr_action": modules["counterfactual_regret_minimization"]["recommended_action"],
            "cfr_confidence": modules["counterfactual_regret_minimization"]["confidence"],
            "prediction_error_trust": modules["prediction_error_model"]["trust_state"],
            "shadow_status": modules["shadow_trade_tracker"]["status"],
        },
    }

