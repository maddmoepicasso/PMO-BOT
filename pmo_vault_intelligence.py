from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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


def _normalize_trade(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    symbol = str(row.get("symbol") or row.get("ticker") or "").upper().strip()
    if not symbol or symbol == "SYSTEM":
        return None
    status = str(row.get("status") or row.get("result") or row.get("outcome") or "").upper()
    pnl = _f(row.get("pnl") or row.get("pnl_usd") or row.get("realized_pnl"), 0)
    closed = status.startswith("CLOSED") or status in {"WIN", "LOSS", "COMPLETE", "COMPLETED"} or pnl != 0
    if not closed:
        return None
    dt = _ts(row.get("entry_timestamp") or row.get("timestamp") or row.get("time"))
    score = _f(row.get("score") or row.get("pmo_score"), 0)
    return {
        "timestamp": row.get("timestamp") or row.get("entry_timestamp") or "",
        "dt": dt,
        "symbol": symbol,
        "status": status,
        "pnl": pnl,
        "win": 1 if pnl > 0 or "WIN" in status else 0,
        "score": score,
        "rvol": _f(row.get("relative_volume") or row.get("rvol"), 0),
        "vwap_distance": _f(row.get("vwap_distance_pct") or row.get("vwap_distance") or row.get("entry_distance_vwap"), 0),
        "regime": str(row.get("market_regime") or row.get("regime") or "UNKNOWN").upper() or "UNKNOWN",
        "pattern_score": _f(row.get("pattern_score_mod") or row.get("pattern_confidence"), 0),
        "sentiment_score": _f(row.get("sentiment_score"), 0),
        "nlp_score": _f(row.get("nlp_score") or row.get("news_score"), 0),
        "ml_win_prob": _f(row.get("ml_win_prob") or row.get("confidence"), 0),
        "gap_signal": str(row.get("gap_signal") or "").upper(),
        "orb_signal": str(row.get("orb_signal") or "").upper(),
        "edge_bull_count": _f(row.get("edge_bull_count"), 0),
        "edge_bear_count": _f(row.get("edge_bear_count"), 0),
    }


def _metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    wins = [row for row in rows if row.get("pnl", 0) > 0]
    losses = [row for row in rows if row.get("pnl", 0) < 0]
    gross_win = sum(row["pnl"] for row in wins)
    gross_loss = abs(sum(row["pnl"] for row in losses))
    return {
        "n": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / max(1, len(rows)), 4),
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss else 999.0 if gross_win else 0.0,
        "avg_pnl": round(sum(row.get("pnl", 0) for row in rows) / max(1, len(rows)), 4),
    }


def _corr(xs: List[float], ys: List[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def _bucket(value: float, cuts: Tuple[float, float]) -> int:
    if value < cuts[0]:
        return 0
    if value < cuts[1]:
        return 1
    return 2


def _mutual_information(feature: List[float], outcome: List[int]) -> float:
    if len(feature) < 10 or len(feature) != len(outcome):
        return 0.0
    sorted_vals = sorted(feature)
    c1 = sorted_vals[len(sorted_vals) // 3]
    c2 = sorted_vals[(len(sorted_vals) * 2) // 3]
    joint = defaultdict(int)
    fx = defaultdict(int)
    fy = defaultdict(int)
    for x, y in zip(feature, outcome):
        xb = _bucket(x, (c1, c2))
        yb = 1 if y else 0
        joint[(xb, yb)] += 1
        fx[xb] += 1
        fy[yb] += 1
    n = len(feature)
    mi = 0.0
    for (xb, yb), count in joint.items():
        pxy = count / n
        px = fx[xb] / n
        py = fy[yb] / n
        if pxy > 0 and px > 0 and py > 0:
            mi += pxy * math.log(pxy / (px * py), 2)
    return round(max(0.0, mi), 4)


def _epigenetic(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    engine_defs = {
        "rvol_gate": lambda row: row.get("rvol", 0),
        "vwap_gate": lambda row: -abs(row.get("vwap_distance", 0)),
        "pattern_engine": lambda row: row.get("pattern_score", 0),
        "sentiment_engine": lambda row: row.get("sentiment_score", 0),
        "nlp_engine": lambda row: row.get("nlp_score", 0),
        "ml_engine": lambda row: row.get("ml_win_prob", 0),
        "edge_confluence": lambda row: row.get("edge_bull_count", 0) - row.get("edge_bear_count", 0),
    }
    outcome = [row["win"] for row in rows]
    states = {}
    for name, fn in engine_defs.items():
        values = [fn(row) for row in rows]
        mi = _mutual_information(values, outcome)
        expression = 0.0 if mi < 0.01 else min(1.8, 0.35 + mi * 3.0)
        states[name] = {
            "active": expression > 0,
            "expression": round(expression, 4),
            "mutual_information": mi,
            "status": "SUPPRESSED" if expression == 0 else "AMPLIFIED" if expression > 1.0 else "EXPRESSED",
        }
    return {
        "status": "READY" if len(rows) >= 50 else "DATA_BUILDING",
        "principle": "Do not remove rules; suppress or amplify engine expression by evidence.",
        "engine_expression": states,
    }


def _strange_attractor(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    series = []
    running = 0.0
    for row in rows[-120:]:
        running += row.get("pnl", 0)
        series.append(running)
    if len(series) < 12:
        lyap = 0.0
    else:
        diffs = [abs(series[i] - series[i - 1]) + 1e-6 for i in range(1, len(series))]
        divergence = [math.log(diffs[i] / diffs[i - 1]) for i in range(1, len(diffs)) if diffs[i - 1] > 0]
        lyap = sum(divergence) / max(1, len(divergence))
    state = "STRONG_ATTRACTOR" if lyap < -0.2 else "CHAOTIC" if lyap > 0.3 else "TRANSITIONAL"
    return {
        "status": "READY" if len(rows) >= 50 else "DATA_BUILDING",
        "lyapunov_proxy": round(lyap, 4),
        "attractor_state": state,
        "trade_filter_guidance": "Trend setups preferred" if state == "STRONG_ATTRACTOR" else "Avoid forcing entries" if state == "CHAOTIC" else "Require confirmation",
    }


def _bayesian_surprise(rows: List[Dict[str, Any]], current_state: Dict[str, Any]) -> Dict[str, Any]:
    current_rvol = _f(current_state.get("rvol"), rows[-1]["rvol"] if rows else 0)
    prior = [row["rvol"] for row in rows if row.get("rvol", 0) > 0]
    if len(prior) < 10:
        z = 0.0
    else:
        mean = sum(prior) / len(prior)
        var = sum((x - mean) ** 2 for x in prior) / len(prior)
        z = (current_rvol - mean) / math.sqrt(var + 1e-6)
    surprise = min(10.0, abs(z))
    return {
        "status": "READY" if len(prior) >= 20 else "DATA_BUILDING",
        "observed_rvol": round(current_rvol, 4),
        "surprise_z": round(z, 4),
        "bayesian_surprise_score": round(surprise, 4),
        "signal": "ANOMALOUS_ACTIVITY" if surprise >= 2.0 else "ORDINARY_ACTIVITY",
    }


def _eigenportfolio(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_symbol: Dict[str, List[float]] = defaultdict(list)
    for row in rows[-300:]:
        by_symbol[row["symbol"]].append(row["pnl"])
    market = []
    max_len = max((len(v) for v in by_symbol.values()), default=0)
    for i in range(max_len):
        vals = [series[i] for series in by_symbol.values() if i < len(series)]
        market.append(sum(vals) / max(1, len(vals)))
    residuals = []
    for symbol, series in by_symbol.items():
        aligned_market = market[: len(series)]
        corr = _corr(series, aligned_market)
        explained = min(1.0, abs(corr))
        residuals.append({
            "symbol": symbol,
            "samples": len(series),
            "market_explained_pct": round(explained, 4),
            "idiosyncratic_pct": round(1.0 - explained, 4),
        })
    residuals.sort(key=lambda item: item["idiosyncratic_pct"], reverse=True)
    return {
        "status": "READY" if len(by_symbol) >= 3 and len(rows) >= 50 else "DATA_BUILDING",
        "component_1": "market_beta_proxy",
        "symbol_count": len(by_symbol),
        "top_idiosyncratic": residuals[:10],
        "guidance": "Prefer moves less explained by dominant market component.",
    }


def _hurst_proxy(values: List[float]) -> float:
    if len(values) < 20:
        return 0.5
    diffs = [values[i] - values[i - 1] for i in range(1, len(values))]
    signs = [1 if x > 0 else -1 if x < 0 else 0 for x in diffs]
    same = sum(1 for i in range(1, len(signs)) if signs[i] == signs[i - 1] and signs[i] != 0)
    return min(1.0, max(0.0, same / max(1, len(signs) - 1)))


def _symmetry_breaking(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    recent = rows[-40:]
    if not recent:
        return {"status": "DATA_BUILDING", "symmetry_score": 0, "signal": "NO_DATA"}
    bull = sum(row.get("edge_bull_count", 0) for row in recent)
    bear = sum(row.get("edge_bear_count", 0) for row in recent)
    asym = abs(bull - bear) / max(1.0, bull + bear)
    vols = [max(0.0, row.get("rvol", 0)) for row in recent]
    avg = sum(vols) / max(1, len(vols))
    power_tail = sum(1 for v in vols if v > avg * 2.5) / max(1, len(vols))
    pnl_curve = []
    running = 0.0
    for row in recent:
        running += row.get("pnl", 0)
        pnl_curve.append(running)
    hurst = _hurst_proxy(pnl_curve)
    score = (asym * 0.45) + (power_tail * 0.25) + (max(0, hurst - 0.5) * 0.60)
    return {
        "status": "READY" if len(rows) >= 50 else "DATA_BUILDING",
        "order_flow_asymmetry_proxy": round(asym, 4),
        "power_law_volume_proxy": round(power_tail, 4),
        "hurst_proxy": round(hurst, 4),
        "symmetry_score": round(score, 4),
        "signal": "SYMMETRY_BREAK_WATCH" if score >= 0.55 else "NO_BREAK",
    }


def _mutual_information_layer(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    outcome = [row["win"] for row in rows]
    features = {
        "score": [row["score"] for row in rows],
        "rvol": [row["rvol"] for row in rows],
        "vwap_distance_abs": [abs(row["vwap_distance"]) for row in rows],
        "pattern_score": [row["pattern_score"] for row in rows],
        "sentiment_score": [row["sentiment_score"] for row in rows],
        "nlp_score": [row["nlp_score"] for row in rows],
        "ml_win_prob": [row["ml_win_prob"] for row in rows],
        "edge_delta": [row["edge_bull_count"] - row["edge_bear_count"] for row in rows],
    }
    scores = [
        {"feature": name, "mutual_information": _mutual_information(values, outcome)}
        for name, values in features.items()
    ]
    scores.sort(key=lambda item: item["mutual_information"], reverse=True)
    return {
        "status": "READY" if len(rows) >= 50 else "DATA_BUILDING",
        "feature_scores": scores,
        "top_feature": scores[0]["feature"] if scores else "",
        "guidance": "Weight high-information features up; suppress near-zero features.",
    }


def _mechanism_design(rows: List[Dict[str, Any]], current_state: Dict[str, Any]) -> Dict[str, Any]:
    score = _f(current_state.get("score"), rows[-1]["score"] if rows else 0)
    rvol = _f(current_state.get("rvol"), rows[-1]["rvol"] if rows else 0)
    spread_proxy = max(0.01, 1.0 / max(1.0, rvol))
    probe_pct = 0.10 if score >= 65 and rvol >= 1.2 else 0.0
    return {
        "status": "SIMULATION_ONLY",
        "probe_size_pct": probe_pct,
        "liquidity_response_window_seconds": 30,
        "spread_proxy": round(spread_proxy, 4),
        "confirming_response": "price absorbs probe without immediate adverse reversal",
        "safety": "No staged/probe orders are placed by this layer. Existing PMO executor remains the only order path.",
    }


def analyze_vault_intelligence(
    trade_journal_path: Path,
    settings: Optional[Dict[str, Any]] = None,
    current_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    settings = settings or {}
    current_state = current_state or {}
    rows = [item for item in (_normalize_trade(row) for row in _read_csv(trade_journal_path, int(_f(settings.get("PMO_VAULT_MAX_ROWS"), 5000)))) if item is not None]
    rows.sort(key=lambda row: row.get("dt") or datetime.min)
    modules = {
        "epigenetic_algorithm": _epigenetic(rows),
        "strange_attractor_detection": _strange_attractor(rows),
        "bayesian_surprise": _bayesian_surprise(rows, current_state),
        "eigenportfolio_decomposition": _eigenportfolio(rows),
        "symmetry_breaking": _symmetry_breaking(rows),
        "mutual_information_maximization": _mutual_information_layer(rows),
        "mechanism_design_probe": _mechanism_design(rows, current_state),
    }
    blockers = []
    if len(rows) < 200:
        blockers.append(f"only {len(rows)} closed trades; vault layer is data-building until 200+")
    if modules["strange_attractor_detection"].get("attractor_state") == "CHAOTIC":
        blockers.append("chaotic attractor state: require extra confirmation")
    return {
        "ok": True,
        "engine": "PMO_VAULT_INTELLIGENCE",
        "status": "READY_READ_ONLY" if rows else "DATA_BUILDING",
        "read_only": True,
        "orders_placed": False,
        "settings_changed": False,
        "live_trading_changed": False,
        "closed_trades": len(rows),
        "summary": _metrics(rows),
        "module_count": len(modules),
        "blockers": blockers,
        "modules": modules,
        "journal": {
            "vault_status": "READY_READ_ONLY" if rows else "DATA_BUILDING",
            "vault_closed_trades": len(rows),
            "vault_top_information_feature": modules["mutual_information_maximization"].get("top_feature", ""),
            "vault_attractor_state": modules["strange_attractor_detection"].get("attractor_state", ""),
            "vault_symmetry_signal": modules["symmetry_breaking"].get("signal", ""),
            "vault_probe_status": modules["mechanism_design_probe"].get("status", "SIMULATION_ONLY"),
        },
    }

