"""
PMO Custom AI Model Engine
==========================
Research-only model lab for PMO Bot.

This module trains lightweight, auditable binary models from PMO's closed paper
trade journal. It never places broker orders, never changes execution settings,
and never unlocks live trading.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


DEFAULT_FEATURES = [
    "score",
    "relative_volume",
    "vwap_distance",
    "entry_distance_vwap",
    "pattern_score_mod",
    "sentiment_score",
    "ml_win_prob",
    "mfe",
    "mae",
    "entry_hour",
    "day_of_week",
    "side_long",
    "asset_stock",
    "asset_crypto",
]

SUPPORTED_MODEL_TYPES = ["AUTO", "KNN", "LOGISTIC", "RANDOM_FOREST"]
SAFE_DEPLOY_MODES = {"REVIEW_ONLY", "PAPER_REVIEW", "SCORE_RESEARCH"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            clean = value.replace("%", "").replace("$", "").replace(",", "").strip()
            if clean == "":
                return default
            return float(clean)
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def sigmoid(value: float) -> float:
    value = max(-60.0, min(60.0, value))
    return 1.0 / (1.0 + math.exp(-value))


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)


def read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8", errors="replace") as handle:
        return list(csv.DictReader(handle))


def model_dir(report_dir: Path) -> Path:
    return Path(report_dir) / "pmo_custom_ai_models"


def registry_path(report_dir: Path) -> Path:
    return Path(report_dir) / "pmo_custom_ai_models.json"


def load_registry(report_dir: Path) -> Dict[str, Any]:
    registry = read_json(registry_path(report_dir), {})
    if not isinstance(registry, dict):
        registry = {}
    registry.setdefault("version", "custom_model_lab_v1")
    registry.setdefault("updated_at", utc_now())
    registry.setdefault("models", [])
    registry.setdefault("deployed_model_id", None)
    registry.setdefault("deployment_mode", "REVIEW_ONLY")
    return registry


def save_registry(report_dir: Path, registry: Dict[str, Any]) -> None:
    registry["updated_at"] = utc_now()
    write_json(registry_path(report_dir), registry)


def model_file(report_dir: Path, model_id: str) -> Path:
    return model_dir(report_dir) / f"{model_id}.json"


def load_model(report_dir: Path, model_id: str) -> Dict[str, Any]:
    return read_json(model_file(report_dir, model_id), {})


def parse_timestamp(row: Dict[str, Any]) -> Optional[datetime]:
    raw = str(row.get("timestamp") or row.get("submitted_at") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def clean_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def closed_trade_rows(
    trade_journal_path: Path,
    custom_rows: Optional[Iterable[Dict[str, Any]]] = None,
    exclude_symbols: Optional[Iterable[Any]] = None,
) -> List[Dict[str, Any]]:
    rows = read_csv_rows(Path(trade_journal_path))
    if custom_rows:
        rows.extend([dict(row) for row in custom_rows if isinstance(row, dict)])
    excluded = {clean_symbol(symbol) for symbol in (exclude_symbols or []) if clean_symbol(symbol)}
    closed: List[Dict[str, Any]] = []
    for row in rows:
        status = str(row.get("status") or "").upper()
        symbol = clean_symbol(row.get("symbol") or row.get("ticker"))
        if not symbol or symbol == "SYSTEM":
            continue
        if symbol in excluded:
            continue
        if status in {"CLOSED_WIN", "CLOSED_LOSS"} or status.startswith("CLOSED"):
            closed.append(row)
    closed.sort(key=lambda item: str(item.get("timestamp") or ""))
    return closed


def normalize_feature_name(name: Any) -> str:
    return str(name or "").strip().lower().replace(" ", "_").replace("-", "_")


def selected_features(spec: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> List[str]:
    raw_features = spec.get("features") or spec.get("inputs") or []
    if isinstance(raw_features, str):
        raw_features = [part.strip() for part in raw_features.split(",") if part.strip()]
    features = [normalize_feature_name(name) for name in raw_features if normalize_feature_name(name)]
    if bool(spec.get("auto_select_inputs", True)) or not features:
        features = list(DEFAULT_FEATURES)
        numeric_counts: Dict[str, int] = {}
        for row in rows[:250]:
            for key, value in row.items():
                name = normalize_feature_name(key)
                if name in features or name in {"timestamp", "status", "symbol", "detail", "sync_key"}:
                    continue
                if value not in (None, "") and safe_float(value, None) is not None:
                    numeric_counts[name] = numeric_counts.get(name, 0) + 1
        for name, _count in sorted(numeric_counts.items(), key=lambda item: item[1], reverse=True)[:8]:
            if name not in features:
                features.append(name)
    return features[:24]


def row_feature_value(row: Dict[str, Any], feature: str) -> float:
    f = normalize_feature_name(feature)
    if f == "entry_hour":
        ts = parse_timestamp(row)
        return float(ts.hour) if ts else 0.0
    if f == "day_of_week":
        ts = parse_timestamp(row)
        return float(ts.weekday()) if ts else 0.0
    if f == "side_long":
        side = str(row.get("side") or "").upper()
        return 1.0 if side in {"LONG", "BUY", "CALL", "CALL_BIAS"} else 0.0
    if f == "asset_stock":
        asset = str(row.get("asset_class") or row.get("market") or "").upper()
        return 1.0 if "STOCK" in asset or asset in {"", "EQUITY"} else 0.0
    if f == "asset_crypto":
        asset = str(row.get("asset_class") or row.get("market") or "").upper()
        symbol = str(row.get("symbol") or "")
        return 1.0 if "CRYPTO" in asset or "/" in symbol else 0.0

    candidates = [
        f,
        f.upper(),
        f.lower(),
        f.replace("_", ""),
        "pmo_" + f,
    ]
    for key in candidates:
        if key in row:
            return safe_float(row.get(key), 0.0)
    for key, value in row.items():
        if normalize_feature_name(key) == f:
            return safe_float(value, 0.0)
    return 0.0


def build_dataset(rows: Sequence[Dict[str, Any]], spec: Dict[str, Any]) -> Tuple[List[List[float]], List[int], List[Dict[str, Any]], List[str]]:
    desired = safe_float(spec.get("desired_result_pct"), 0.0)
    reward = safe_float(spec.get("reward_pct"), desired or 5.0)
    risk = safe_float(spec.get("risk_pct"), 1.0)
    features = selected_features(spec, rows)
    vectors: List[List[float]] = []
    labels: List[int] = []
    used_rows: List[Dict[str, Any]] = []
    for row in rows:
        pnl = safe_float(row.get("pnl"), 0.0)
        pnl_pct = safe_float(row.get("pnl_pct"), None)
        if pnl_pct is None:
            entry = safe_float(row.get("entry_price"), 0.0)
            exit_price = safe_float(row.get("exit_price"), 0.0)
            side = str(row.get("side") or "").upper()
            if entry > 0 and exit_price > 0:
                pnl_pct = ((exit_price - entry) / entry) * 100.0
                if side in {"SHORT", "SELL", "PUT", "PUT_BIAS"}:
                    pnl_pct *= -1.0
            else:
                pnl_pct = 100.0 if pnl > 0 else (-100.0 if pnl < 0 else 0.0)
        target = desired if desired > 0 else max(0.01, reward - risk)
        label = 1 if pnl_pct >= target else 0
        vector = [row_feature_value(row, feature) for feature in features]
        vectors.append(vector)
        labels.append(label)
        used_rows.append(row)
    return vectors, labels, used_rows, features


def scale_fit(vectors: Sequence[Sequence[float]]) -> Dict[str, Any]:
    if not vectors:
        return {"mean": [], "std": []}
    width = len(vectors[0])
    means: List[float] = []
    stds: List[float] = []
    for idx in range(width):
        values = [safe_float(row[idx], 0.0) for row in vectors]
        mean = sum(values) / max(1, len(values))
        variance = sum((value - mean) ** 2 for value in values) / max(1, len(values))
        std = math.sqrt(variance) or 1.0
        means.append(mean)
        stds.append(std)
    return {"mean": means, "std": stds}


def scale_apply(vectors: Sequence[Sequence[float]], scaler: Dict[str, Any]) -> List[List[float]]:
    means = scaler.get("mean") or []
    stds = scaler.get("std") or []
    scaled: List[List[float]] = []
    for row in vectors:
        scaled.append([
            (safe_float(value, 0.0) - safe_float(means[idx], 0.0)) / (safe_float(stds[idx], 1.0) or 1.0)
            for idx, value in enumerate(row)
        ])
    return scaled


def split_dataset(vectors: List[List[float]], labels: List[int]) -> Tuple[List[List[float]], List[int], List[List[float]], List[int]]:
    if len(vectors) < 8:
        return vectors, labels, vectors, labels
    split = max(4, int(len(vectors) * 0.75))
    if split >= len(vectors):
        split = len(vectors) - 1
    return vectors[:split], labels[:split], vectors[split:], labels[split:]


def accuracy(predictions: Sequence[float], labels: Sequence[int]) -> float:
    if not labels:
        return 0.0
    hits = 0
    for prob, label in zip(predictions, labels):
        hits += int((prob >= 0.5) == bool(label))
    return round(hits / len(labels), 4)


def predict_knn(model: Dict[str, Any], vector: Sequence[float]) -> float:
    points = model.get("training_vectors") or []
    labels = model.get("training_labels") or []
    k = max(1, safe_int(model.get("k"), 5))
    if not points or not labels:
        return 0.0
    distances = []
    for idx, point in enumerate(points):
        dist = math.sqrt(sum((safe_float(vector[i], 0.0) - safe_float(point[i], 0.0)) ** 2 for i in range(min(len(vector), len(point)))))
        distances.append((dist, labels[idx]))
    nearest = sorted(distances, key=lambda item: item[0])[:k]
    return sum(label for _dist, label in nearest) / max(1, len(nearest))


def train_knn(train_x: List[List[float]], train_y: List[int], spec: Dict[str, Any]) -> Dict[str, Any]:
    k = max(1, min(15, safe_int(spec.get("knn_k"), 5)))
    return {"algorithm": "KNN", "k": k, "training_vectors": train_x, "training_labels": train_y}


def train_logistic(train_x: List[List[float]], train_y: List[int]) -> Dict[str, Any]:
    if not train_x:
        return {"algorithm": "LOGISTIC", "weights": [], "bias": 0.0}
    width = len(train_x[0])
    weights = [0.0] * width
    bias = 0.0
    learning_rate = 0.08
    epochs = 350
    for _ in range(epochs):
        grad_w = [0.0] * width
        grad_b = 0.0
        for vector, label in zip(train_x, train_y):
            z = bias + sum(weights[idx] * safe_float(vector[idx], 0.0) for idx in range(width))
            pred = sigmoid(z)
            err = pred - label
            for idx in range(width):
                grad_w[idx] += err * safe_float(vector[idx], 0.0)
            grad_b += err
        n = max(1, len(train_x))
        for idx in range(width):
            weights[idx] -= learning_rate * (grad_w[idx] / n)
        bias -= learning_rate * (grad_b / n)
    return {"algorithm": "LOGISTIC", "weights": [round(w, 6) for w in weights], "bias": round(bias, 6)}


def predict_logistic(model: Dict[str, Any], vector: Sequence[float]) -> float:
    weights = model.get("weights") or []
    bias = safe_float(model.get("bias"), 0.0)
    return sigmoid(bias + sum(safe_float(weights[idx], 0.0) * safe_float(vector[idx], 0.0) for idx in range(min(len(weights), len(vector)))))


def train_random_forest_lite(train_x: List[List[float]], train_y: List[int], feature_names: Sequence[str]) -> Dict[str, Any]:
    if not train_x:
        return {"algorithm": "RANDOM_FOREST_LITE", "stumps": []}
    rng = random.Random(1126)
    width = len(train_x[0])
    stumps: List[Dict[str, Any]] = []
    for _ in range(40):
        feature_idx = rng.randrange(width)
        values = sorted(row[feature_idx] for row in train_x)
        if not values:
            continue
        threshold = values[rng.randrange(len(values))]
        best_polarity = 1
        best_acc = -1.0
        for polarity in (1, -1):
            preds = [1 if (row[feature_idx] >= threshold) == (polarity == 1) else 0 for row in train_x]
            acc = accuracy(preds, train_y)
            if acc > best_acc:
                best_acc = acc
                best_polarity = polarity
        stumps.append({
            "feature_idx": feature_idx,
            "feature": feature_names[feature_idx] if feature_idx < len(feature_names) else str(feature_idx),
            "threshold": round(threshold, 6),
            "polarity": best_polarity,
            "train_accuracy": best_acc,
        })
    stumps.sort(key=lambda item: item.get("train_accuracy", 0.0), reverse=True)
    return {"algorithm": "RANDOM_FOREST_LITE", "stumps": stumps[:25], "note": "Dependency-free bagged-stump model used for auditability."}


def predict_random_forest_lite(model: Dict[str, Any], vector: Sequence[float]) -> float:
    stumps = model.get("stumps") or []
    if not stumps:
        return 0.0
    votes = []
    for stump in stumps:
        idx = safe_int(stump.get("feature_idx"), 0)
        threshold = safe_float(stump.get("threshold"), 0.0)
        polarity = safe_int(stump.get("polarity"), 1)
        vote = 1 if (safe_float(vector[idx], 0.0) >= threshold) == (polarity == 1) else 0
        weight = max(0.01, safe_float(stump.get("train_accuracy"), 0.5))
        votes.append((vote, weight))
    return sum(vote * weight for vote, weight in votes) / max(0.0001, sum(weight for _vote, weight in votes))


def model_predict_probability(model: Dict[str, Any], vector: Sequence[float]) -> float:
    algo = str(model.get("algorithm") or model.get("model_type") or "").upper()
    if model.get("ensemble_children"):
        children = model.get("ensemble_children") or []
        if not children:
            return 0.0
        weighted = 0.0
        total = 0.0
        for child in children:
            weight = max(0.01, safe_float(child.get("weight"), 1.0))
            child_model = child.get("model") or {}
            weighted += model_predict_probability(child_model, vector) * weight
            total += weight
        return weighted / max(0.0001, total)
    if algo == "KNN":
        return predict_knn(model, vector)
    if algo == "LOGISTIC":
        return predict_logistic(model, vector)
    if algo in {"RANDOM_FOREST", "RANDOM_FOREST_LITE"}:
        return predict_random_forest_lite(model, vector)
    return 0.0


def feature_importance(model: Dict[str, Any], feature_names: Sequence[str], train_x: List[List[float]], train_y: List[int]) -> List[Dict[str, Any]]:
    algo = str(model.get("algorithm") or "").upper()
    rows: List[Dict[str, Any]] = []
    if algo == "LOGISTIC":
        weights = model.get("weights") or []
        for idx, weight in enumerate(weights):
            rows.append({"feature": feature_names[idx] if idx < len(feature_names) else str(idx), "importance": round(abs(safe_float(weight)), 4), "direction": "positive" if safe_float(weight) >= 0 else "negative"})
    elif algo in {"RANDOM_FOREST", "RANDOM_FOREST_LITE"}:
        counts: Dict[str, float] = {}
        for stump in model.get("stumps") or []:
            name = str(stump.get("feature") or "")
            counts[name] = counts.get(name, 0.0) + safe_float(stump.get("train_accuracy"), 0.5)
        rows = [{"feature": name, "importance": round(value, 4), "direction": "stump_vote"} for name, value in counts.items()]
    else:
        for idx, name in enumerate(feature_names):
            positives = [row[idx] for row, label in zip(train_x, train_y) if label == 1]
            negatives = [row[idx] for row, label in zip(train_x, train_y) if label == 0]
            delta = (sum(positives) / max(1, len(positives))) - (sum(negatives) / max(1, len(negatives)))
            rows.append({"feature": name, "importance": round(abs(delta), 4), "direction": "positive" if delta >= 0 else "negative"})
    return sorted(rows, key=lambda item: item.get("importance", 0), reverse=True)[:12]


def fit_single_model(model_type: str, train_x: List[List[float]], train_y: List[int], val_x: List[List[float]], val_y: List[int], feature_names: Sequence[str], spec: Dict[str, Any]) -> Dict[str, Any]:
    requested = str(model_type or "AUTO").upper()
    if requested == "KNN":
        model = train_knn(train_x, train_y, spec)
    elif requested == "LOGISTIC":
        model = train_logistic(train_x, train_y)
    else:
        model = train_random_forest_lite(train_x, train_y, feature_names)
        model["algorithm"] = "RANDOM_FOREST"
        model["implementation"] = "RANDOM_FOREST_LITE"

    train_pred = [model_predict_probability(model, row) for row in train_x]
    val_pred = [model_predict_probability(model, row) for row in val_x]
    model["train_accuracy"] = accuracy(train_pred, train_y)
    model["validation_accuracy"] = accuracy(val_pred, val_y)
    model["avg_validation_probability"] = round(sum(val_pred) / max(1, len(val_pred)), 4)
    model["feature_importance"] = feature_importance(model, feature_names, train_x, train_y)
    return model


def build_model_id(name: str, model_type: str) -> str:
    seed = f"{utc_now()}|{name}|{model_type}"
    suffix = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    clean_name = "".join(ch for ch in str(name or "model").lower().replace(" ", "_") if ch.isalnum() or ch == "_")[:24] or "model"
    return f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{clean_name}_{suffix}"


def train_custom_ai_model(report_dir: Path, trade_journal_path: Path, spec: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    spec = dict(spec or {})
    model_type = str(spec.get("model_type") or spec.get("algorithm") or "AUTO").upper()
    if model_type not in SUPPORTED_MODEL_TYPES:
        return {"ok": False, "error": f"Unsupported model_type {model_type}. Use {', '.join(SUPPORTED_MODEL_TYPES)}.", "orders_placed": False, "live_unlocked": False}

    custom_rows = spec.get("custom_rows") if isinstance(spec.get("custom_rows"), list) else None
    exclude_symbols = spec.get("exclude_symbols") or []
    if isinstance(exclude_symbols, str):
        exclude_symbols = [part.strip() for part in exclude_symbols.replace(";", ",").split(",") if part.strip()]
    exclude_symbols = [clean_symbol(symbol) for symbol in exclude_symbols if clean_symbol(symbol)]
    all_closed_rows = closed_trade_rows(Path(trade_journal_path), custom_rows)
    rows = closed_trade_rows(Path(trade_journal_path), custom_rows, exclude_symbols=exclude_symbols)
    excluded_row_count = max(0, len(all_closed_rows) - len(rows))
    vectors, labels, used_rows, features = build_dataset(rows, spec)
    warnings: List[str] = []
    if len(vectors) < 20:
        warnings.append("Less than 20 closed outcomes; model is research-only and low confidence.")
    if len(set(labels)) < 2:
        warnings.append("Only one target class found; validation accuracy is not reliable.")
    if not vectors:
        return {"ok": False, "error": "No closed trade rows available for training.", "closed_rows": len(rows), "orders_placed": False, "live_unlocked": False}

    scaler = scale_fit(vectors)
    scaled = scale_apply(vectors, scaler)
    train_x, train_y, val_x, val_y = split_dataset(scaled, labels)
    candidates: List[Dict[str, Any]] = []
    model_types = ["KNN", "LOGISTIC", "RANDOM_FOREST"] if model_type == "AUTO" else [model_type]
    for candidate_type in model_types:
        candidates.append(fit_single_model(candidate_type, train_x, train_y, val_x, val_y, features, spec))
    best = sorted(candidates, key=lambda item: (safe_float(item.get("validation_accuracy"), 0), safe_float(item.get("train_accuracy"), 0)), reverse=True)[0]

    name = str(spec.get("model_name") or f"PMO {model_type} Custom Model").strip()
    model_id = build_model_id(name, best.get("algorithm", model_type))
    positive_rows = sum(labels)
    negative_rows = len(labels) - positive_rows
    baseline = max(positive_rows, negative_rows) / max(1, len(labels))
    record = {
        "ok": True,
        "model_id": model_id,
        "model_name": name,
        "created_at": utc_now(),
        "research_only": True,
        "paper_review_only": True,
        "orders_placed": False,
        "live_unlocked": False,
        "live_trading_changed": False,
        "score_influence": False,
        "requested_model_type": model_type,
        "selected_model_type": best.get("algorithm"),
        "implementation": best.get("implementation", best.get("algorithm")),
        "trade_horizon_days": safe_int(spec.get("trade_horizon_days"), 30),
        "desired_result_pct": safe_float(spec.get("desired_result_pct"), 5.0),
        "risk_pct": safe_float(spec.get("risk_pct"), 1.0),
        "reward_pct": safe_float(spec.get("reward_pct"), 5.0),
        "reward_risk_ratio": round(safe_float(spec.get("reward_pct"), 5.0) / max(0.0001, safe_float(spec.get("risk_pct"), 1.0)), 4),
        "features": features,
        "training_filter": "EXCLUDE_SYMBOL_BLOCKLIST" if exclude_symbols else "ALL_CLOSED_TRADES",
        "excluded_symbols": exclude_symbols,
        "total_closed_rows_before_filter": len(all_closed_rows),
        "excluded_row_count": excluded_row_count,
        "training_rows": len(rows),
        "usable_rows": len(vectors),
        "positive_rows": positive_rows,
        "negative_rows": negative_rows,
        "baseline_accuracy": round(baseline, 4),
        "train_accuracy": best.get("train_accuracy"),
        "validation_accuracy": best.get("validation_accuracy"),
        "model": best,
        "scaler": scaler,
        "candidate_results": [
            {
                "algorithm": item.get("algorithm"),
                "implementation": item.get("implementation", item.get("algorithm")),
                "train_accuracy": item.get("train_accuracy"),
                "validation_accuracy": item.get("validation_accuracy"),
            }
            for item in candidates
        ],
        "feature_importance": best.get("feature_importance", []),
        "warnings": warnings,
        "deployment": {
            "status": "NOT_DEPLOYED",
            "mode": "REVIEW_ONLY",
            "live_deploy_blocked": True,
        },
        "safe_note": "Custom AI models are research/paper-review only. They do not place orders or unlock live trading.",
    }
    write_json(model_file(report_dir, model_id), record)

    registry = load_registry(report_dir)
    registry["models"] = [item for item in registry.get("models", []) if item.get("model_id") != model_id]
    registry["models"].insert(0, {
        "model_id": model_id,
        "model_name": name,
        "created_at": record["created_at"],
        "selected_model_type": record["selected_model_type"],
        "implementation": record["implementation"],
        "validation_accuracy": record["validation_accuracy"],
        "train_accuracy": record["train_accuracy"],
        "usable_rows": record["usable_rows"],
        "positive_rows": record["positive_rows"],
        "desired_result_pct": record["desired_result_pct"],
        "trade_horizon_days": record["trade_horizon_days"],
        "deployment": record["deployment"],
    })
    save_registry(report_dir, registry)
    return record


def list_custom_ai_models(report_dir: Path, limit: int = 25) -> Dict[str, Any]:
    registry = load_registry(report_dir)
    models = registry.get("models", [])[: max(1, safe_int(limit, 25))]
    return {
        "ok": True,
        "research_only": True,
        "orders_placed": False,
        "live_unlocked": False,
        "score_influence": False,
        "model_count": len(registry.get("models", [])),
        "deployed_model_id": registry.get("deployed_model_id"),
        "deployment_mode": registry.get("deployment_mode", "REVIEW_ONLY"),
        "models": models,
        "registry_file": str(registry_path(report_dir)),
    }


def custom_model_lab_status(
    report_dir: Path,
    csv_dir: Path,
    trade_journal_path: Optional[Path] = None,
    exclude_symbols: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    registry = load_registry(report_dir)
    trade_journal = Path(trade_journal_path) if trade_journal_path else Path(csv_dir) / "pmo_bot_trade_journal.csv"
    all_rows = closed_trade_rows(trade_journal)
    clean_rows = closed_trade_rows(trade_journal, exclude_symbols=exclude_symbols or [])
    latest = registry.get("models", [None])[0] if registry.get("models") else None
    excluded = [clean_symbol(symbol) for symbol in (exclude_symbols or []) if clean_symbol(symbol)]
    return {
        "ok": True,
        "enabled": True,
        "research_only": True,
        "paper_review_only": True,
        "orders_placed": False,
        "live_unlocked": False,
        "live_trading_changed": False,
        "score_influence": False,
        "supported_model_types": SUPPORTED_MODEL_TYPES,
        "default_features": DEFAULT_FEATURES,
        "closed_trade_authority": "REAL_TRADE_JOURNAL",
        "closed_rows_available": len(clean_rows),
        "total_closed_rows_before_filter": len(all_rows),
        "excluded_row_count": max(0, len(all_rows) - len(clean_rows)),
        "excluded_symbols": excluded,
        "training_filter": "EXCLUDE_SYMBOL_BLOCKLIST" if excluded else "ALL_CLOSED_TRADES",
        "model_count": len(registry.get("models", [])),
        "latest_model": latest,
        "deployed_model_id": registry.get("deployed_model_id"),
        "deployment_mode": registry.get("deployment_mode", "REVIEW_ONLY"),
        "registry_file": str(registry_path(report_dir)),
        "safe_note": "Train, merge, and deploy are review-only. Live execution remains locked behind PMO safety gates.",
    }


def delete_custom_ai_model(report_dir: Path, model_id: str) -> Dict[str, Any]:
    registry = load_registry(report_dir)
    before = len(registry.get("models", []))
    registry["models"] = [item for item in registry.get("models", []) if item.get("model_id") != model_id]
    if registry.get("deployed_model_id") == model_id:
        registry["deployed_model_id"] = None
        registry["deployment_mode"] = "REVIEW_ONLY"
    save_registry(report_dir, registry)
    path = model_file(report_dir, model_id)
    deleted_file = False
    if path.exists():
        path.unlink()
        deleted_file = True
    return {
        "ok": True,
        "deleted": before != len(registry.get("models", [])) or deleted_file,
        "model_id": model_id,
        "orders_placed": False,
        "live_unlocked": False,
        "score_influence": False,
    }


def deploy_custom_ai_model(report_dir: Path, model_id: str, mode: str = "REVIEW_ONLY") -> Dict[str, Any]:
    mode = str(mode or "REVIEW_ONLY").upper()
    if mode not in SAFE_DEPLOY_MODES:
        mode = "REVIEW_ONLY"
    registry = load_registry(report_dir)
    model = load_model(report_dir, model_id)
    if not model:
        return {"ok": False, "error": f"Model {model_id} not found.", "orders_placed": False, "live_unlocked": False}
    deployment = {
        "status": "DEPLOYED_FOR_REVIEW",
        "mode": mode,
        "deployed_at": utc_now(),
        "live_deploy_blocked": True,
        "orders_placed": False,
        "live_unlocked": False,
        "score_influence": False,
    }
    model["deployment"] = deployment
    write_json(model_file(report_dir, model_id), model)
    registry["deployed_model_id"] = model_id
    registry["deployment_mode"] = mode
    for item in registry.get("models", []):
        if item.get("model_id") == model_id:
            item["deployment"] = deployment
    save_registry(report_dir, registry)
    return {"ok": True, "model_id": model_id, "deployment": deployment, "orders_placed": False, "live_unlocked": False, "live_trading_changed": False}


def merge_custom_ai_models(report_dir: Path, model_ids: Sequence[str], merged_name: str = "PMO Merged Review Model") -> Dict[str, Any]:
    children = []
    for model_id in model_ids:
        model = load_model(report_dir, str(model_id))
        if not model:
            continue
        weight = max(0.01, safe_float(model.get("validation_accuracy"), 0.5))
        children.append({"model_id": model.get("model_id"), "weight": weight, "model": model.get("model", {})})
    if len(children) < 2:
        return {"ok": False, "error": "Need at least two existing models to merge.", "orders_placed": False, "live_unlocked": False}

    base = load_model(report_dir, str(model_ids[0]))
    model_id = build_model_id(merged_name, "ENSEMBLE")
    record = {
        "ok": True,
        "model_id": model_id,
        "model_name": merged_name,
        "created_at": utc_now(),
        "research_only": True,
        "paper_review_only": True,
        "orders_placed": False,
        "live_unlocked": False,
        "score_influence": False,
        "selected_model_type": "ENSEMBLE",
        "implementation": "WEIGHTED_ENSEMBLE",
        "features": base.get("features", DEFAULT_FEATURES),
        "scaler": base.get("scaler", {"mean": [], "std": []}),
        "model": {"algorithm": "ENSEMBLE", "ensemble_children": children},
        "merged_from": list(model_ids),
        "deployment": {"status": "NOT_DEPLOYED", "mode": "REVIEW_ONLY", "live_deploy_blocked": True},
        "safe_note": "Merged model is review-only and cannot place orders.",
    }
    write_json(model_file(report_dir, model_id), record)
    registry = load_registry(report_dir)
    registry["models"].insert(0, {
        "model_id": model_id,
        "model_name": merged_name,
        "created_at": record["created_at"],
        "selected_model_type": "ENSEMBLE",
        "implementation": "WEIGHTED_ENSEMBLE",
        "validation_accuracy": round(sum(child["weight"] for child in children) / len(children), 4),
        "train_accuracy": None,
        "usable_rows": base.get("usable_rows"),
        "positive_rows": base.get("positive_rows"),
        "deployment": record["deployment"],
    })
    save_registry(report_dir, registry)
    return record


def predict_custom_ai_model(report_dir: Path, model_id: Optional[str] = None, features: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    registry = load_registry(report_dir)
    model_id = model_id or registry.get("deployed_model_id")
    if not model_id:
        models = registry.get("models") or []
        model_id = models[0].get("model_id") if models else None
    if not model_id:
        return {"ok": False, "error": "No custom model available.", "orders_placed": False, "live_unlocked": False}
    record = load_model(report_dir, str(model_id))
    if not record:
        return {"ok": False, "error": f"Model {model_id} not found.", "orders_placed": False, "live_unlocked": False}
    features = dict(features or {})
    feature_names = record.get("features") or DEFAULT_FEATURES
    raw_vector = [[row_feature_value(features, feature) for feature in feature_names]]
    scaled = scale_apply(raw_vector, record.get("scaler") or {})
    probability = model_predict_probability(record.get("model") or {}, scaled[0] if scaled else [])
    return {
        "ok": True,
        "model_id": model_id,
        "model_name": record.get("model_name"),
        "probability": round(probability, 4),
        "decision": "FAVORABLE_REVIEW" if probability >= 0.6 else ("NEUTRAL_REVIEW" if probability >= 0.45 else "UNFAVORABLE_REVIEW"),
        "features_used": feature_names,
        "research_only": True,
        "orders_placed": False,
        "live_unlocked": False,
        "live_trading_changed": False,
        "score_influence": False,
        "safe_note": "Prediction is advisory only. PMO execution gates still decide paper eligibility.",
    }


def profit_factor_from_returns(returns: Sequence[float]) -> float:
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    if gains > 0 and losses == 0:
        return 999.0
    return round(gains / losses, 4) if losses else 0.0


def max_drawdown_from_returns(returns: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return round(max_dd, 4)


def sharpe_like(returns: Sequence[float]) -> float:
    if not returns:
        return 0.0
    avg = sum(returns) / len(returns)
    variance = sum((value - avg) ** 2 for value in returns) / max(1, len(returns))
    std = math.sqrt(variance)
    return round(avg / std, 4) if std else (999.0 if avg > 0 else 0.0)


def sortino_like(returns: Sequence[float]) -> float:
    if not returns:
        return 0.0
    avg = sum(returns) / len(returns)
    downside = [min(0.0, value) for value in returns]
    variance = sum(value ** 2 for value in downside) / max(1, len(downside))
    std = math.sqrt(variance)
    return round(avg / std, 4) if std else (999.0 if avg > 0 else 0.0)


def strategy_bucket(rows: Sequence[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[float]] = {}
    for row in rows:
        value = str(row.get(key) or "UNKNOWN").strip() or "UNKNOWN"
        returns = safe_float(row.get("pnl_pct"), 0.0)
        buckets.setdefault(value, []).append(returns)
    output = []
    for name, returns in buckets.items():
        output.append({
            "bucket": name,
            "trades": len(returns),
            "win_rate": round(sum(1 for value in returns if value > 0) / max(1, len(returns)), 4),
            "avg_return_pct": round(sum(returns) / max(1, len(returns)), 4),
            "profit_factor": profit_factor_from_returns(returns),
        })
    return sorted(output, key=lambda item: item.get("avg_return_pct", 0), reverse=True)


def run_custom_strategy_tester(report_dir: Path, trade_journal_path: Path, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Backtest/refinement report for custom strategy ideas and JS indicator artifacts.

    The JavaScript source is stored and hashed for research traceability, but not executed
    inside PMO Bot. Vetted indicator logic should be translated into PMO Python rules
    before it can influence Why-Not or paper execution.
    """
    payload = dict(payload or {})
    rows = closed_trade_rows(Path(trade_journal_path), payload.get("custom_rows") if isinstance(payload.get("custom_rows"), list) else None)
    returns = [safe_float(row.get("pnl_pct"), 0.0) for row in rows]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    indicator_js = str(payload.get("indicator_javascript") or payload.get("javascript") or "")
    js_hash = hashlib.sha256(indicator_js.encode("utf-8")).hexdigest()[:16] if indicator_js else ""
    trades = len(returns)
    win_rate = round(len(wins) / max(1, trades), 4)
    avg_return = round(sum(returns) / max(1, trades), 4)
    pf = profit_factor_from_returns(returns)
    max_dd = max_drawdown_from_returns(returns)
    sharpe = sharpe_like(returns)
    sortino = sortino_like(returns)
    desired_pf = safe_float(payload.get("min_profit_factor"), 1.1)
    desired_win_rate = safe_float(payload.get("min_win_rate"), 0.45)
    desired_return = safe_float(payload.get("min_avg_return_pct"), 0.0)

    no_go_flags = []
    green_flags = []
    if trades < 20:
        no_go_flags.append("Too few closed outcomes for reliable strategy validation.")
    if pf < desired_pf:
        no_go_flags.append(f"Profit factor {pf} below required {desired_pf}.")
    else:
        green_flags.append(f"Profit factor {pf} meets required {desired_pf}.")
    if win_rate < desired_win_rate:
        no_go_flags.append(f"Win rate {round(win_rate * 100, 1)}% below required {round(desired_win_rate * 100, 1)}%.")
    else:
        green_flags.append(f"Win rate {round(win_rate * 100, 1)}% meets requirement.")
    if avg_return <= desired_return:
        no_go_flags.append(f"Average return {avg_return}% does not clear required {desired_return}%.")
    else:
        green_flags.append(f"Average return {avg_return}% clears required {desired_return}%.")
    if sharpe <= 0:
        no_go_flags.append("Sharpe-like ratio is not positive.")
    if sortino <= 0:
        no_go_flags.append("Sortino-like ratio is not positive.")

    randomized = list(returns)
    random.Random(931).shuffle(randomized)
    randomized_max_dd = max_drawdown_from_returns(randomized)
    buy_hold_proxy = {
        "note": "Proxy uses all closed PMO outcomes because this tester is journal-backed, not full market-history-backed.",
        "avg_return_pct": avg_return,
        "sample_trades": trades,
    }
    stop_target_review = {
        "avg_win_pct": round(sum(wins) / max(1, len(wins)), 4),
        "avg_loss_pct": round(sum(losses) / max(1, len(losses)), 4),
        "reward_risk_realized": round((sum(wins) / max(1, len(wins))) / abs(sum(losses) / max(1, len(losses))), 4) if losses else 999.0,
        "suggestion": "Do not widen risk until PF and Sortino are positive." if pf < 1.0 else "Stop/target structure is viable enough for paper-only refinement.",
    }
    avg_win = stop_target_review["avg_win_pct"]
    avg_loss = abs(stop_target_review["avg_loss_pct"])
    exit_sooner_returns = [
        value if value > 0 else max(value, -max(0.1, avg_loss * 0.65))
        for value in returns
    ]
    let_winners_run_returns = [
        value * 1.20 if value > 0 else value
        for value in returns
    ]
    balanced_returns = [
        (value * 1.12 if value > 0 else max(value, -max(0.1, avg_loss * 0.75)))
        for value in returns
    ]
    reward_risk_optimizer = {
        "current": {
            "win_rate": win_rate,
            "avg_win_pct": avg_win,
            "avg_loss_pct": round(avg_loss, 4),
            "profit_factor": pf,
            "realized_rr": stop_target_review["reward_risk_realized"],
        },
        "exit_losers_sooner_sim": {
            "description": "Caps losing outcomes near 65% of current average loss.",
            "profit_factor": profit_factor_from_returns(exit_sooner_returns),
            "avg_return_pct": round(sum(exit_sooner_returns) / max(1, len(exit_sooner_returns)), 4),
            "max_drawdown_pct_points": max_drawdown_from_returns(exit_sooner_returns),
        },
        "let_winners_run_sim": {
            "description": "Expands winning outcomes by 20% while leaving losses unchanged.",
            "profit_factor": profit_factor_from_returns(let_winners_run_returns),
            "avg_return_pct": round(sum(let_winners_run_returns) / max(1, len(let_winners_run_returns)), 4),
            "max_drawdown_pct_points": max_drawdown_from_returns(let_winners_run_returns),
        },
        "balanced_exit_sim": {
            "description": "Combines earlier loser exits with modest winner extension.",
            "profit_factor": profit_factor_from_returns(balanced_returns),
            "avg_return_pct": round(sum(balanced_returns) / max(1, len(balanced_returns)), 4),
            "max_drawdown_pct_points": max_drawdown_from_returns(balanced_returns),
        },
        "interpretation": "Use the scenario with better PF and lower drawdown as a paper-only exit hypothesis before changing live or automated behavior.",
    }
    entry_timing = {
        "late_entry_buckets": strategy_bucket(rows, "late_entry_flag")[:8],
        "vwap_distance_buckets": strategy_bucket(rows, "entry_distance_vwap")[:8],
        "price_behavior_explorer": "Focus on buckets with positive avg_return_pct and PF above 1.0; block or retest buckets that drag PF lower.",
    }
    scatter_rows = []
    for row in rows[-300:]:
        scatter_rows.append({
            "symbol": row.get("symbol", ""),
            "score": safe_float(row.get("score"), 0.0),
            "pnl_pct": safe_float(row.get("pnl_pct"), 0.0),
            "relative_volume": safe_float(row.get("relative_volume"), 0.0),
            "vwap_distance": safe_float(row.get("vwap_distance") or row.get("entry_distance_vwap"), 0.0),
            "setup_type": row.get("setup_type", ""),
            "asset_class": row.get("asset_class", row.get("market", "")),
        })
    symbol_variance = strategy_bucket(rows, "symbol")[:25]
    asset_variance = strategy_bucket(rows, "asset_class")[:12]
    requested_timeframes = payload.get("timeframes") if isinstance(payload.get("timeframes"), list) else ["journal_native"]
    margin_of_safety = {
        "profit_factor_margin": round(pf - desired_pf, 4),
        "win_rate_margin": round(win_rate - desired_win_rate, 4),
        "avg_return_margin": round(avg_return - desired_return, 4),
        "status": "POSITIVE" if pf >= desired_pf and win_rate >= desired_win_rate and avg_return > desired_return else "NEGATIVE",
    }
    report = {
        "ok": True,
        "generated_at": utc_now(),
        "strategy_name": str(payload.get("strategy_name") or "PMO Custom Strategy"),
        "research_only": True,
        "orders_placed": False,
        "live_unlocked": False,
        "live_trading_changed": False,
        "score_influence": False,
        "javascript_indicator": {
            "stored": bool(indicator_js),
            "sha256_16": js_hash,
            "line_count": len(indicator_js.splitlines()) if indicator_js else 0,
            "execution": "DISABLED_IN_TRADING_SERVER",
            "reason": "Arbitrary JavaScript must be reviewed and translated into vetted PMO rules before it can influence trade gates.",
        },
        "kpis": {
            "closed_trades": trades,
            "win_rate": win_rate,
            "avg_return_pct": avg_return,
            "profit_factor": pf,
            "max_drawdown_pct_points": max_dd,
            "sharpe_like": sharpe,
            "sortino_like": sortino,
            "best_trade_pct": round(max(returns), 4) if returns else 0.0,
            "worst_trade_pct": round(min(returns), 4) if returns else 0.0,
        },
        "controls": {
            "buy_hold_proxy": buy_hold_proxy,
            "randomized_control": {
                "same_returns_shuffled_max_drawdown": randomized_max_dd,
                "note": "Randomized control checks path risk, not edge superiority.",
            },
        },
        "margin_of_safety": margin_of_safety,
        "no_go_flags": no_go_flags,
        "green_flags": green_flags,
        "reward_risk_optimizer": reward_risk_optimizer,
        "entry_timing": entry_timing,
        "stop_target_review": stop_target_review,
        "condition_breakdown": {
            "score_buckets": strategy_bucket(rows, "score_bucket")[:10],
            "setup_types": strategy_bucket(rows, "setup_type")[:10],
            "asset_classes": strategy_bucket(rows, "asset_class")[:10],
            "symbols": strategy_bucket(rows, "symbol")[:12],
        },
        "multi_symbol_timeframe": {
            "requested_symbols": payload.get("symbols") if isinstance(payload.get("symbols"), list) else "all_closed_journal_symbols",
            "requested_timeframes": requested_timeframes,
            "symbol_variance": symbol_variance,
            "asset_class_variance": asset_variance,
            "timeframe_note": "Journal-backed tester can compare symbols now. Full timeframe variance requires historical bar datasets by timeframe.",
        },
        "scatter_plot_rows": scatter_rows,
        "strategy_bot_deployment": {
            "supported_review_modes": ["ALERT_ONLY", "POSITION_AWARE_ALERTS", "PAPER_REVIEW_BOT"],
            "live_bot_deploy": "BLOCKED_BY_PMO_LIVE_GATES",
            "no_coding_ui_ready": True,
            "rules_required_before_automation": [
                "entry conditions",
                "exit conditions",
                "stop loss",
                "take profit",
                "position sizing",
                "asset universe",
                "proof threshold",
            ],
            "safe_note": "PMO can package a strategy as alert-only or paper-review automation first. Live order placement stays locked behind PMO live readiness and owner approval.",
        },
        "ai_strategy_support": {
            "on_demand_review": True,
            "can_summarize_tables": True,
            "can_identify_misconfigurations": True,
            "machine_vision_chart_review": "Not enabled in this local backend route. Use uploaded chart review separately before converting visual observations into PMO rules.",
        },
        "refinement_plan": [
            "Keep this strategy in paper/research until no-go flags are cleared.",
            "Translate useful JavaScript indicator conditions into explicit PMO Python gates before production use.",
            "Use reward/risk optimizer scenarios to choose paper-only exit hypotheses.",
            "Compare strategy against symbol and asset-class variance before increasing paper size.",
            "Compare new closed outcomes against this report after 20 more paper trades.",
            "Use entry timing buckets to block late/chased setups before changing stop size.",
        ],
    }
    output_dir = Path(report_dir) / "pmo_custom_strategy_tests"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_id = hashlib.sha256((report["generated_at"] + report["strategy_name"] + js_hash).encode("utf-8")).hexdigest()[:10]
    report["report_id"] = report_id
    report["report_file"] = str(output_dir / f"{report_id}.json")
    write_json(Path(report["report_file"]), report)
    return report


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    result = custom_model_lab_status(here / "pmo_reports", here / "pmo_csv")
    print(json.dumps(result, indent=2))
