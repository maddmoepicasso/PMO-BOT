from __future__ import annotations

import csv
import math
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace("%", "").strip())
    except Exception:
        return default


def _i(value: Any, default: int = 0) -> int:
    return int(_f(value, default))


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
            rows = list(csv.DictReader(handle))
    except Exception:
        return []
    return rows[-limit:]


def _normalize_trade(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
    if not symbol or symbol == "SYSTEM":
        return None
    status = str(row.get("status") or row.get("result") or row.get("outcome") or "").upper()
    pnl = _f(row.get("pnl") or row.get("pnl_usd") or row.get("realized_pnl"), 0)
    is_closed = status.startswith("CLOSED") or status in {"WIN", "LOSS", "COMPLETE", "COMPLETED"} or pnl != 0
    if not is_closed:
        return None
    win = 1 if pnl > 0 or "WIN" in status or "TARGET" in status else 0
    score = _f(row.get("score") or row.get("pmo_score"), 0)
    return {
        "timestamp": row.get("timestamp") or row.get("time") or "",
        "dt": _ts(row.get("timestamp") or row.get("time")),
        "symbol": symbol,
        "status": status,
        "side": str(row.get("side") or "").upper(),
        "score": score,
        "score_bucket": _score_bucket(score),
        "pnl": pnl,
        "pnl_pct": _f(row.get("pnl_pct") or row.get("return_pct"), 0),
        "win": win,
        "regime": str(row.get("market_regime") or row.get("regime") or "UNKNOWN").upper() or "UNKNOWN",
        "rvol": _f(row.get("relative_volume") or row.get("rvol"), 0),
        "vwap_distance": _f(row.get("vwap_distance_pct") or row.get("vwap_distance") or row.get("entry_distance_vwap"), 0),
        "mfe": _f(row.get("mfe") or row.get("max_favorable_excursion"), 0),
        "mae": _f(row.get("mae") or row.get("max_adverse_excursion"), 0),
        "gap_signal": str(row.get("gap_signal") or "").upper(),
        "orb_signal": str(row.get("orb_signal") or "").upper(),
        "pattern": str(row.get("pattern_name") or "").upper(),
        "sentiment": str(row.get("sentiment_signal") or "").upper(),
        "ml_signal": str(row.get("ml_signal") or "").upper(),
        "edge_signal": str(row.get("edge_signal") or "").upper(),
        "confluence": str(row.get("confluence_status") or "").upper(),
    }


def _score_bucket(score: float) -> str:
    if score < 40:
        return "<40"
    if score < 55:
        return "40-54"
    if score < 65:
        return "55-64"
    if score < 75:
        return "65-74"
    if score < 78:
        return "75-77"
    if score < 93:
        return "78-92"
    return "93+"


def _metrics(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(rows)
    closed = len(rows)
    wins = sum(1 for row in rows if row.get("win"))
    gross_profit = sum(max(0.0, _f(row.get("pnl"), 0)) for row in rows)
    gross_loss = abs(sum(min(0.0, _f(row.get("pnl"), 0)) for row in rows))
    return {
        "closed": closed,
        "wins": wins,
        "losses": closed - wins,
        "win_rate": round(wins / closed, 4) if closed else 0.0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (999.0 if gross_profit else 0.0),
        "net_pnl": round(gross_profit - gross_loss, 4),
        "avg_pnl": round((gross_profit - gross_loss) / closed, 4) if closed else 0.0,
    }


def _model_status(n: int, minimum: int = 20) -> str:
    if n >= minimum:
        return "READY"
    if n >= max(5, minimum // 4):
        return "DATA_BUILDING"
    return "INSUFFICIENT_DATA"


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, x))))


def _base_probability(row: Dict[str, Any], regime_win_rate: float, decay_win_rate: float) -> float:
    score_component = (_f(row.get("score"), 60) - 60.0) / 45.0
    rvol_component = min(1.0, _f(row.get("rvol"), 0) / 3.0) - 0.35
    vwap_component = -abs(_f(row.get("vwap_distance"), 0)) / 4.0
    history_component = ((regime_win_rate + decay_win_rate) / 2.0) - 0.5
    return _sigmoid(score_component + rvol_component + vwap_component + history_component)


def _vector(row: Dict[str, Any]) -> List[float]:
    return [
        _f(row.get("score"), 0) / 100.0,
        min(5.0, _f(row.get("rvol"), 0)) / 5.0,
        max(-1.0, min(1.0, _f(row.get("vwap_distance"), 0) / 5.0)),
        max(-1.0, min(1.0, _f(row.get("mfe"), 0) / 10.0)),
        max(-1.0, min(1.0, _f(row.get("mae"), 0) / 10.0)),
        1.0 if "GAP_UP" in str(row.get("gap_signal")) else -1.0 if "GAP_DOWN" in str(row.get("gap_signal")) else 0.0,
        1.0 if str(row.get("orb_signal")) == "BULLISH" else -1.0 if str(row.get("orb_signal")) == "BEARISH" else 0.0,
    ]


def _dist(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _regime_models(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    regimes: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        regimes.setdefault(str(row.get("regime") or "UNKNOWN"), []).append(row)
    return {
        regime: {
            **_metrics(items),
            "status": _model_status(len(items), 20),
            "recommended_use": "route_to_regime_model" if len(items) >= 20 else "collect_more_regime_outcomes",
        }
        for regime, items in sorted(regimes.items())
    }


def _embeddings(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"status": "INSUFFICIENT_DATA", "vectors": 0, "nearest": []}
    latest = rows[-1]
    latest_vec = _vector(latest)
    peers = sorted(
        ((row, _dist(latest_vec, _vector(row))) for row in rows[:-1]),
        key=lambda item: item[1],
    )[:5]
    return {
        "status": _model_status(len(rows), 30),
        "vectors": len(rows),
        "latest_symbol": latest.get("symbol"),
        "embedding_dims": len(latest_vec),
        "nearest": [
            {
                "symbol": row.get("symbol"),
                "score": row.get("score"),
                "pnl": row.get("pnl"),
                "win": row.get("win"),
                "distance": round(distance, 4),
            }
            for row, distance in peers
        ],
    }


def _kalman(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    values = [_f(row.get("vwap_distance"), 0) for row in rows if row.get("vwap_distance") not in ("", None)]
    if not values:
        return {"status": "DATA_REQUIRED", "fair_value_offset": 0.0, "uncertainty": 1.0}
    estimate = values[0]
    covariance = 1.0
    process_noise = 0.03
    measurement_noise = 0.35
    for value in values[1:]:
        covariance += process_noise
        gain = covariance / (covariance + measurement_noise)
        estimate = estimate + gain * (value - estimate)
        covariance = (1 - gain) * covariance
    return {
        "status": _model_status(len(values), 20),
        "fair_value_offset": round(estimate, 4),
        "uncertainty": round(math.sqrt(max(covariance, 0.0)), 4),
        "samples": len(values),
        "signal": "FAIR_VALUE_STABLE" if abs(estimate) <= 0.5 and covariance <= 0.25 else "WIDE_UNCERTAINTY",
    }


def _rl_exit_policy(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    actions = {"BAIL": [], "PARTIAL": [], "HOLD": []}
    for row in rows:
        pnl = _f(row.get("pnl"), 0)
        mfe = _f(row.get("mfe"), 0)
        mae = abs(_f(row.get("mae"), 0))
        if pnl < 0 or mae > max(2.0, mfe * 1.5):
            actions["BAIL"].append(pnl)
        elif mfe > abs(pnl) * 1.5 and pnl > 0:
            actions["PARTIAL"].append(pnl)
        else:
            actions["HOLD"].append(pnl)
    q_values = {action: round(sum(vals) / len(vals), 4) if vals else 0.0 for action, vals in actions.items()}
    best = max(q_values, key=lambda key: q_values[key]) if q_values else "HOLD"
    return {
        "status": _model_status(len(rows), 50),
        "policy": "Q_LEARNING_EXIT_TIMING_READ_ONLY",
        "best_action": best,
        "q_values": q_values,
        "samples": {action: len(vals) for action, vals in actions.items()},
        "note": "Read-only exit policy; not changing stops, targets, or partial exits.",
    }


def _uncertainty(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"status": "INSUFFICIENT_DATA"}
    recent = rows[-50:]
    win_rate = _metrics(recent)["win_rate"]
    n = len(recent)
    z = 1.64
    se = math.sqrt(max(0.0001, win_rate * (1 - win_rate) / max(1, n)))
    lower = max(0.0, win_rate - z * se)
    upper = min(1.0, win_rate + z * se)
    rng = random.Random(17)
    dropout_runs = []
    latest = recent[-1]
    regime_wr = _metrics([row for row in recent if row.get("regime") == latest.get("regime")])["win_rate"] or win_rate
    for _ in range(50):
        noisy = dict(latest)
        if rng.random() < 0.35:
            noisy["rvol"] = 0
        if rng.random() < 0.35:
            noisy["vwap_distance"] = 0
        if rng.random() < 0.35:
            noisy["score"] = 60
        dropout_runs.append(_base_probability(noisy, regime_wr, win_rate))
    mean = sum(dropout_runs) / len(dropout_runs)
    variance = sum((x - mean) ** 2 for x in dropout_runs) / len(dropout_runs)
    return {
        "status": _model_status(n, 30),
        "conformal_interval": {"lower": round(lower, 4), "upper": round(upper, 4), "confidence": 0.90, "n": n},
        "monte_carlo_dropout": {"runs": 50, "mean": round(mean, 4), "variance": round(variance, 6), "skip_if_variance_above": 0.02, "signal": "SKIP_UNCERTAIN" if variance > 0.02 else "ACCEPTABLE_UNCERTAINTY"},
    }


def _walk_forward(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row.get("dt") or datetime.min)
    folds = []
    train_window = 40
    test_window = 10
    for start in range(0, max(0, len(ordered) - train_window - test_window + 1), test_window):
        train = ordered[start:start + train_window]
        test = ordered[start + train_window:start + train_window + test_window]
        if len(test) < test_window:
            continue
        train_wr = _metrics(train)["win_rate"]
        test_wr = _metrics(test)["win_rate"]
        folds.append({"train": len(train), "test": len(test), "train_wr": train_wr, "test_wr": test_wr, "decay": round(test_wr - train_wr, 4)})
    return {
        "status": "READY" if folds else _model_status(len(rows), train_window + test_window),
        "folds": folds[-8:],
        "fold_count": len(folds),
        "avg_test_wr": round(sum(f["test_wr"] for f in folds) / len(folds), 4) if folds else 0.0,
    }


def _decay_weighting(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(rows, key=lambda row: row.get("dt") or datetime.min)
    weighted_wins = weighted_count = weighted_pnl = 0.0
    total = len(ordered)
    for idx, row in enumerate(ordered):
        age_rank = total - idx - 1
        weight = 3.0 if age_rank < 20 else 2.0 if age_rank < 50 else 1.0
        weighted_wins += weight * int(row.get("win", 0))
        weighted_count += weight
        weighted_pnl += weight * _f(row.get("pnl"), 0)
    return {
        "status": _model_status(total, 30),
        "weighted_win_rate": round(weighted_wins / weighted_count, 4) if weighted_count else 0.0,
        "weighted_avg_pnl": round(weighted_pnl / weighted_count, 4) if weighted_count else 0.0,
        "recent_weight": "last_20=3x,last_50=2x,older=1x",
    }


def _stacking(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    engines = ["gap_signal", "orb_signal", "pattern", "sentiment", "ml_signal", "edge_signal", "confluence"]
    weights = {}
    for engine in engines:
        active = [row for row in rows if str(row.get(engine) or "").strip()]
        metric = _metrics(active)
        weights[engine] = {
            "samples": len(active),
            "win_rate": metric["win_rate"],
            "weight": round(max(0.0, metric["win_rate"] - 0.45) * min(1.0, len(active) / 30), 4),
            "status": _model_status(len(active), 30),
        }
    total_weight = sum(item["weight"] for item in weights.values())
    return {
        "status": _model_status(len(rows), 50),
        "meta_learner": "STACKED_ENGINE_TRUST_READ_ONLY",
        "weights": weights,
        "total_weight": round(total_weight, 4),
        "recommendation": "use highest weighted engines per regime" if total_weight > 0 else "collect more labeled outcomes",
    }


def _kelly_uncertainty(rows: List[Dict[str, Any]], uncertainty: Dict[str, Any]) -> Dict[str, Any]:
    metrics = _metrics(rows)
    win_rate = metrics["win_rate"]
    avg_win = sum(_f(row.get("pnl"), 0) for row in rows if _f(row.get("pnl"), 0) > 0)
    win_count = max(1, sum(1 for row in rows if _f(row.get("pnl"), 0) > 0))
    avg_loss = abs(sum(_f(row.get("pnl"), 0) for row in rows if _f(row.get("pnl"), 0) < 0))
    loss_count = max(1, sum(1 for row in rows if _f(row.get("pnl"), 0) < 0))
    b = (avg_win / win_count) / max(0.01, avg_loss / loss_count)
    raw = win_rate - ((1 - win_rate) / b) if b > 0 else 0.0
    interval = uncertainty.get("conformal_interval", {}) if isinstance(uncertainty, dict) else {}
    width = _f(interval.get("upper"), 1) - _f(interval.get("lower"), 0)
    confidence_discount = max(0.1, min(1.0, 1.0 - width))
    return {
        "status": _model_status(len(rows), 30),
        "raw_kelly": round(max(0.0, raw), 4),
        "confidence_discount": round(confidence_discount, 4),
        "discounted_kelly": round(max(0.0, raw) * confidence_discount, 4),
        "size_tier": "FULL" if confidence_discount >= 0.75 else "HALF" if confidence_discount >= 0.45 else "QUARTER",
    }


def _mdl(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    candidate_features = 12
    n = max(1, len(rows))
    complexity = candidate_features * math.log2(n + 1)
    data_bits = n * max(0.1, abs(_metrics(rows)["avg_pnl"]) + 1.0)
    ratio = complexity / max(1.0, data_bits)
    return {
        "status": _model_status(len(rows), 100),
        "feature_count": candidate_features,
        "sample_count": len(rows),
        "mdl_ratio": round(ratio, 4),
        "overfit_risk": "HIGH" if ratio > 1.0 or len(rows) < 100 else "MEDIUM" if ratio > 0.5 else "LOW",
    }


def _synthetic(rows: List[Dict[str, Any]], target: int = 200) -> Dict[str, Any]:
    if len(rows) < 10:
        return {"status": "INSUFFICIENT_DATA", "generated": 0, "method": "BOOTSTRAP_SMOTE_STYLE", "excluded_from_proof": True}
    rng = random.Random(23)
    generated = []
    numeric = ["score", "rvol", "vwap_distance", "mfe", "mae", "pnl"]
    for _ in range(target):
        a, b = rng.sample(rows, 2)
        lam = rng.random()
        generated.append({field: _f(a.get(field), 0) * lam + _f(b.get(field), 0) * (1 - lam) for field in numeric})
    return {
        "status": "READY_READ_ONLY",
        "generated": len(generated),
        "method": "BOOTSTRAP_SMOTE_STYLE",
        "real_rows": len(rows),
        "synthetic_avg_score": round(sum(row["score"] for row in generated) / len(generated), 4),
        "synthetic_avg_pnl": round(sum(row["pnl"] for row in generated) / len(generated), 4),
        "excluded_from_proof": True,
        "warning": "Synthetic rows are for stress/testing only; they are not counted as proof.",
    }


def analyze_advanced_ml_intelligence(
    trade_journal_path: Path,
    order_journal_path: Optional[Path] = None,
    symbol: str = "",
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    settings = settings or {}
    raw_rows = _read_csv(trade_journal_path, int(_f(settings.get("PMO_ADVANCED_ML_MAX_ROWS"), 5000)))
    rows = [item for item in (_normalize_trade(row) for row in raw_rows) if item is not None]
    rows.sort(key=lambda row: row.get("dt") or datetime.min)
    if symbol:
        filtered = [row for row in rows if row.get("symbol") == symbol.upper()]
        if filtered:
            rows = filtered

    regime_models = _regime_models(rows)
    embedding = _embeddings(rows)
    kalman = _kalman(rows)
    exit_policy = _rl_exit_policy(rows)
    uncertainty = _uncertainty(rows)
    walk_forward = _walk_forward(rows)
    decay = _decay_weighting(rows)
    stacking = _stacking(rows)
    kelly = _kelly_uncertainty(rows, uncertainty)
    mdl = _mdl(rows)
    synthetic = _synthetic(rows, int(_f(settings.get("PMO_ADVANCED_ML_SYNTHETIC_ROWS"), 200)))

    modules = {
        "regime_conditional_models": regime_models,
        "price_action_embeddings": embedding,
        "kalman_vwap": kalman,
        "rl_exit_timing": exit_policy,
        "conformal_prediction": uncertainty.get("conformal_interval", {}),
        "monte_carlo_dropout": uncertainty.get("monte_carlo_dropout", {}),
        "time_series_cross_validation": walk_forward,
        "decay_weighting": decay,
        "stacked_engine_meta_learner": stacking,
        "kelly_with_uncertainty": kelly,
        "minimum_description_length": mdl,
        "synthetic_trade_generation": synthetic,
    }
    ready_count = sum(1 for value in modules.values() if str(value.get("status", "READY") if isinstance(value, dict) else "READY").startswith("READY"))
    blockers = []
    if len(rows) < 50:
        blockers.append(f"only {len(rows)} closed trades; advanced ML needs 50+ and prefers 200+")
    if mdl.get("overfit_risk") == "HIGH":
        blockers.append("MDL overfit risk HIGH; keep layer read-only")
    if uncertainty.get("monte_carlo_dropout", {}).get("signal") == "SKIP_UNCERTAIN":
        blockers.append("dropout variance too high for confident sizing")

    return {
        "ok": True,
        "engine": "PMO_ADVANCED_ML_INTELLIGENCE",
        "status": "READY_READ_ONLY" if ready_count >= 6 else "DATA_BUILDING",
        "read_only": True,
        "orders_placed": False,
        "live_trading_changed": False,
        "symbol": symbol.upper() if symbol else "ALL",
        "closed_trades": len(rows),
        "summary": _metrics(rows),
        "ready_count": ready_count,
        "module_count": len(modules),
        "blockers": blockers,
        "modules": modules,
        "journal": {
            "advanced_ml_status": "READY_READ_ONLY" if ready_count >= 6 else "DATA_BUILDING",
            "advanced_ml_ready_count": ready_count,
            "advanced_ml_closed_trades": len(rows),
            "advanced_ml_overfit_risk": mdl.get("overfit_risk"),
            "advanced_ml_kelly_discount": kelly.get("confidence_discount"),
            "advanced_ml_dropout_signal": uncertainty.get("monte_carlo_dropout", {}).get("signal"),
            "stacking_status": stacking.get("status"),
            "walk_forward_status": walk_forward.get("status"),
            "walk_forward_folds": walk_forward.get("fold_count", 0),
        },
    }
