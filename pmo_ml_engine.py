"""
PMO ML Engine — pmo_ml_engine.py
==================================
Lightweight ML win-probability model trained on PMO Bot's own closed trades.
Uses scikit-learn (already installed). No external data, no GPU required.

Read-only: predictions are logged to journal and shown on dashboard.
Does NOT affect PMO score until validated on 50+ trades.

Honest limitations (important):
  - Trained on YOUR closed trades (currently ~43). This is very small.
  - Model will overfit at this data size — treat predictions as directional
    hints, not reliable probabilities.
  - Reliability improves significantly at 100+ trades, becomes meaningful at 200+.
  - The model is retrained automatically each time PMO Bot restarts (or on demand).
  - Features used: pmo_score, pattern_direction, sentiment_score, nlp_score,
    rvol, vwap_position, hold_time_min, entry_time_bucket, day_of_week.

Output:
  win_probability  : 0.0–1.0 (estimated probability trade is a winner)
  ml_signal        : FAVORABLE / NEUTRAL / UNFAVORABLE
  ml_confidence    : LOW / MEDIUM / HIGH (based on training data size)
  feature_importance: dict of which features mattered most
  model_trained    : bool (False if insufficient training data)
  training_trades  : int

Usage:
    from pmo_ml_engine import MLEngine
    engine = MLEngine()
    engine.train(closed_trades_csv_path)   # or pass list of dicts
    result = engine.predict(features_dict)
    print(result)
    print(result.get_journal_dict())
"""

import os
import csv
import logging
import math
from dataclasses import dataclass, field
from typing import Optional, Any

logger = logging.getLogger("pmo.ml_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_TRADES_TO_TRAIN  = 20    # absolute minimum — model exists but unreliable
MIN_TRADES_RELIABLE  = 100   # minimum for meaningful predictions
MIN_TRADES_GOOD      = 200   # minimum for production-quality predictions

FAVORABLE_THRESHOLD   = 0.58  # win_prob >= 0.58 → FAVORABLE
UNFAVORABLE_THRESHOLD = 0.42  # win_prob <= 0.42 → UNFAVORABLE

# Features expected in the predict() input dict
# All are optional — missing features are filled with dataset medians
FEATURE_NAMES = [
    "pmo_score",           # float: raw PMO score (pre-pattern-mod)
    "pattern_score_mod",   # int: pattern engine modifier (-8 to +8)
    "sentiment_score",     # int: composite sentiment (-100 to +100)
    "nlp_score",           # int: NLP headline score (-100 to +100)
    "rvol",                # float: relative volume at entry
    "vwap_position",       # float: (entry_price - vwap) / vwap * 100
    "hold_time_min",       # float: planned or actual hold time in minutes
    "entry_hour",          # int: hour of day (9–15)
    "day_of_week",         # int: 0=Mon, 4=Fri
    "score_band",          # int: 0=65-74, 1=75-84, 2=85-92 (PMO band)
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class MLResult:
    win_probability:    float           = 0.5
    ml_signal:          str             = "NEUTRAL"
    ml_confidence:      str             = "LOW"
    model_trained:      bool            = False
    training_trades:    int             = 0
    feature_importance: dict            = field(default_factory=dict)
    features_used:      dict            = field(default_factory=dict)
    warning:            Optional[str]   = None

    def get_journal_dict(self) -> dict:
        return {
            "ml_win_prob":      round(self.win_probability, 3),
            "ml_signal":        self.ml_signal,
            "ml_confidence":    self.ml_confidence,
            "ml_trained_on":    self.training_trades,
            "ml_top_feature":   self._top_feature(),
        }

    def get_dashboard_dict(self) -> dict:
        return {
            "win_prob":     round(self.win_probability * 100, 1),
            "signal":       self.ml_signal,
            "confidence":   self.ml_confidence,
            "trained_on":   self.training_trades,
            "model_ready":  self.model_trained,
            "warning":      self.warning,
            "top_features": dict(list(self.feature_importance.items())[:3]),
        }

    def _top_feature(self) -> str:
        if not self.feature_importance:
            return "none"
        return max(self.feature_importance, key=self.feature_importance.get)

    def __str__(self):
        if not self.model_trained:
            return f"ML: not trained ({self.training_trades} trades, need {MIN_TRADES_TO_TRAIN})"
        pct = int(self.win_probability * 100)
        return (f"ML: {self.ml_signal} (win_prob={pct}%, "
                f"confidence={self.ml_confidence}, "
                f"trained_on={self.training_trades})")


# ---------------------------------------------------------------------------
# Feature extraction helpers
# ---------------------------------------------------------------------------

def _parse_float(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _extract_features_from_trade(trade: dict) -> Optional[dict]:
    """
    Extract ML features from a closed trade dict (from trade journal CSV).
    Returns None if the trade doesn't have enough data to use.
    """
    # Determine win/loss
    pnl = _parse_float(trade.get("pnl") or trade.get("profit_loss") or
                        trade.get("realized_pnl") or trade.get("return_pct"))
    if pnl == 0.0:
        return None   # can't determine outcome

    won = 1 if pnl > 0 else 0

    # Entry time features
    entry_time = str(trade.get("entry_time") or trade.get("entry_datetime") or trade.get("timestamp") or "")
    entry_hour = 11   # default mid-morning
    day_of_week = 2   # default Wednesday
    try:
        import datetime
        # Try common datetime formats
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%H:%M:%S", "%H:%M"]:
            try:
                dt = datetime.datetime.strptime(entry_time[:19], fmt)
                entry_hour  = dt.hour
                day_of_week = dt.weekday()
                break
            except ValueError:
                continue
    except Exception:
        pass

    # Score band
    pmo_score = _parse_float(trade.get("score") or trade.get("pmo_score"))
    if pmo_score < 75:
        band = 0
    elif pmo_score < 85:
        band = 1
    else:
        band = 2

    return {
        "pmo_score":         pmo_score,
        "pattern_score_mod": _parse_float(trade.get("pattern_score_mod")),
        "sentiment_score":   _parse_float(trade.get("sentiment_score")),
        "nlp_score":         _parse_float(trade.get("nlp_score")),
        "rvol":              _parse_float(trade.get("rvol") or trade.get("relative_volume"), 1.0),
        "vwap_position":     _parse_float(trade.get("vwap_position") or trade.get("vwap_pct")),
        "hold_time_min":     _parse_float(trade.get("hold_time_min") or trade.get("hold_minutes")),
        "entry_hour":        entry_hour,
        "day_of_week":       day_of_week,
        "score_band":        band,
        "_won":              won,
    }


def _load_trades_from_csv(csv_path: str) -> list:
    """Load closed trades from PMO journal CSV."""
    trades = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades.append(dict(row))
        logger.info("MLEngine: loaded %d rows from %s", len(trades), csv_path)
    except FileNotFoundError:
        logger.warning("MLEngine: CSV not found: %s", csv_path)
    except Exception as e:
        logger.error("MLEngine: CSV load error: %s", e)
    return trades


# ---------------------------------------------------------------------------
# Simple logistic regression (pure Python fallback)
# ---------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


class _SimpleLogisticRegression:
    """
    Pure-Python logistic regression.
    Used as fallback when scikit-learn is unavailable.
    Gradient descent, no regularization (kept simple for small data).
    """

    def __init__(self, lr: float = 0.01, epochs: int = 500):
        self.lr     = lr
        self.epochs = epochs
        self.w: list  = []
        self.b: float = 0.0

    def fit(self, X: list, y: list):
        n_features = len(X[0])
        self.w = [0.0] * n_features
        self.b = 0.0
        n = len(X)
        for _ in range(self.epochs):
            for xi, yi in zip(X, y):
                pred  = _sigmoid(sum(w * x for w, x in zip(self.w, xi)) + self.b)
                error = pred - yi
                for j in range(n_features):
                    self.w[j] -= self.lr * error * xi[j]
                self.b -= self.lr * error

    def predict_proba(self, x: list) -> float:
        z = sum(w * xi for w, xi in zip(self.w, x)) + self.b
        return _sigmoid(z)

    def feature_importances(self) -> list:
        total = sum(abs(w) for w in self.w) or 1.0
        return [abs(w) / total for w in self.w]


# ---------------------------------------------------------------------------
# Main ML Engine
# ---------------------------------------------------------------------------

class MLEngine:
    """
    Trains a win-probability model on PMO's own closed trade history.
    Automatically falls back to scikit-learn GradientBoosting if available,
    otherwise uses the built-in pure-Python logistic regression.

    engine = MLEngine()
    engine.train("pmo_bot_trade_journal.csv")   # or pass list of dicts
    result = engine.predict({
        "pmo_score": 74,
        "rvol": 2.1,
        "pattern_score_mod": 6,
        ...
    })
    """

    def __init__(self):
        self._model         = None
        self._sklearn       = False
        self._trained       = False
        self._training_n    = 0
        self._feature_medians: dict = {f: 0.0 for f in FEATURE_NAMES}
        self._feature_importances: dict = {}
        self._scaler_mean: list = []
        self._scaler_std:  list = []

        # Try to import sklearn
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            from sklearn.preprocessing import StandardScaler
            self._GBC     = GradientBoostingClassifier
            self._Scaler  = StandardScaler
            self._sklearn = True
            logger.info("MLEngine: scikit-learn available, using GradientBoosting")
        except ImportError:
            logger.info("MLEngine: scikit-learn not available, using built-in logistic regression")

    def train(self, source) -> bool:
        """
        Train the model.
        source: str (path to journal CSV) or list of trade dicts.
        Returns True if training succeeded.
        """
        # Load trades
        if isinstance(source, str):
            raw_trades = _load_trades_from_csv(source)
        elif isinstance(source, list):
            raw_trades = source
        else:
            logger.error("MLEngine.train: source must be CSV path or list of dicts")
            return False

        # Extract features
        feature_dicts = []
        for trade in raw_trades:
            fd = _extract_features_from_trade(trade)
            if fd is not None:
                feature_dicts.append(fd)

        if len(feature_dicts) < MIN_TRADES_TO_TRAIN:
            logger.warning(
                "MLEngine: only %d usable trades (need %d to train)",
                len(feature_dicts), MIN_TRADES_TO_TRAIN
            )
            self._training_n = len(feature_dicts)
            return False

        # Build X, y
        X = [[fd[f] for f in FEATURE_NAMES] for fd in feature_dicts]
        y = [fd["_won"] for fd in feature_dicts]

        # Compute feature medians for imputation
        for i, feat in enumerate(FEATURE_NAMES):
            vals = sorted([row[i] for row in X])
            mid  = len(vals) // 2
            self._feature_medians[feat] = (
                vals[mid] if len(vals) % 2 else (vals[mid-1] + vals[mid]) / 2
            )

        # Normalize features (z-score)
        n_feat = len(FEATURE_NAMES)
        means  = [sum(row[i] for row in X) / len(X) for i in range(n_feat)]
        stds   = [
            math.sqrt(sum((row[i] - means[i]) ** 2 for row in X) / len(X)) or 1.0
            for i in range(n_feat)
        ]
        self._scaler_mean = means
        self._scaler_std  = stds
        X_scaled = [[(row[i] - means[i]) / stds[i] for i in range(n_feat)] for row in X]

        # Train
        if self._sklearn:
            try:
                from sklearn.ensemble import GradientBoostingClassifier
                from sklearn.preprocessing import StandardScaler
                import numpy as np

                X_np = np.array(X)
                y_np = np.array(y)

                scaler = self._Scaler()
                X_sc   = scaler.fit_transform(X_np)

                mdl = self._GBC(
                    n_estimators   = min(50, len(feature_dicts) // 2),
                    max_depth      = 2,    # shallow — prevents overfitting on small data
                    learning_rate  = 0.1,
                    subsample      = 0.8,
                    random_state   = 42,
                )
                mdl.fit(X_sc, y_np)
                self._model        = (mdl, scaler)
                importances        = mdl.feature_importances_
                self._feature_importances = {
                    FEATURE_NAMES[i]: round(float(importances[i]), 4)
                    for i in range(n_feat)
                }
                self._sklearn_fit  = True
            except Exception as e:
                logger.warning("MLEngine: sklearn fit failed (%s), falling back", e)
                self._sklearn = False

        if not self._sklearn or self._model is None:
            # Pure-Python logistic regression
            lr_model = _SimpleLogisticRegression(lr=0.05, epochs=800)
            lr_model.fit(X_scaled, y)
            self._model = lr_model
            imps = lr_model.feature_importances()
            self._feature_importances = {
                FEATURE_NAMES[i]: round(imps[i], 4) for i in range(n_feat)
            }
            self._sklearn_fit = False

        self._trained     = True
        self._training_n  = len(feature_dicts)

        win_rate = sum(y) / len(y)
        logger.info(
            "MLEngine: trained on %d trades (win_rate=%.1f%%) using %s",
            len(feature_dicts), win_rate * 100,
            "GradientBoosting" if (self._sklearn and hasattr(self, '_sklearn_fit') and self._sklearn_fit)
            else "LogisticRegression"
        )
        return True

    def _scale_features(self, x_raw: list) -> list:
        if not self._scaler_mean:
            return x_raw
        return [
            (x_raw[i] - self._scaler_mean[i]) / self._scaler_std[i]
            for i in range(len(x_raw))
        ]

    def predict(self, features: dict) -> MLResult:
        """
        Predict win probability for a candidate trade.
        features: dict with any subset of FEATURE_NAMES.
        Missing features filled with training medians.
        """
        # Fill missing features with medians
        filled = {
            feat: features.get(feat, self._feature_medians.get(feat, 0.0))
            for feat in FEATURE_NAMES
        }
        x_raw = [float(filled[f]) for f in FEATURE_NAMES]

        if not self._trained or self._model is None:
            warn = (f"Model not trained ({self._training_n} trades available, "
                    f"need {MIN_TRADES_TO_TRAIN})")
            return MLResult(
                win_probability  = 0.5,
                ml_signal        = "NEUTRAL",
                ml_confidence    = "LOW",
                model_trained    = False,
                training_trades  = self._training_n,
                warning          = warn,
            )

        # Predict
        try:
            if self._sklearn and isinstance(self._model, tuple):
                mdl, scaler = self._model
                import numpy as np
                X_sc = scaler.transform(np.array([x_raw]))
                prob = float(mdl.predict_proba(X_sc)[0][1])
            else:
                x_scaled = self._scale_features(x_raw)
                prob = self._model.predict_proba(x_scaled)
        except Exception as e:
            logger.error("MLEngine.predict error: %s", e)
            prob = 0.5

        prob = max(0.0, min(1.0, prob))

        # Signal
        if prob >= FAVORABLE_THRESHOLD:
            signal = "FAVORABLE"
        elif prob <= UNFAVORABLE_THRESHOLD:
            signal = "UNFAVORABLE"
        else:
            signal = "NEUTRAL"

        # Confidence based on training data size
        if self._training_n >= MIN_TRADES_GOOD:
            confidence = "HIGH"
        elif self._training_n >= MIN_TRADES_RELIABLE:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        # Warning for small training sets
        warning = None
        if self._training_n < MIN_TRADES_RELIABLE:
            warning = (f"Low confidence: only {self._training_n} training trades. "
                       f"Treat as directional hint only.")

        return MLResult(
            win_probability    = round(prob, 4),
            ml_signal          = signal,
            ml_confidence      = confidence,
            model_trained      = True,
            training_trades    = self._training_n,
            feature_importance = self._feature_importances,
            features_used      = filled,
            warning            = warning,
        )

    def retrain(self, source) -> bool:
        """Alias for train() — used for periodic retraining."""
        self._trained = False
        self._model   = None
        return self.train(source)

    @property
    def is_trained(self) -> bool:
        return self._trained

    @property
    def training_trades(self) -> int:
        return self._training_n


# ---------------------------------------------------------------------------
# Integration helper for pmo_bot.py
# ---------------------------------------------------------------------------

def build_ml_features(score: float, pattern_result=None,
                       sentiment_result=None, nlp_result=None,
                       trade_dict: dict = None) -> dict:
    """
    Convenience function to build the features dict from PMO's existing objects.
    Call this just before engine.predict().

    Example in pmo_bot.py:
        features = build_ml_features(
            score=pmo_score,
            pattern_result=pattern,
            sentiment_result=sentiment,
            nlp_result=nlp,
            trade_dict={"rvol": 2.1, "vwap_position": 0.3, "entry_hour": 10}
        )
        ml_result = ml_engine.predict(features)
    """
    td = trade_dict or {}
    features = {
        "pmo_score":         score,
        "pattern_score_mod": getattr(pattern_result, "score_modifier", 0) if pattern_result else 0,
        "sentiment_score":   getattr(sentiment_result, "sentiment_score", 0) if sentiment_result else 0,
        "nlp_score":         getattr(nlp_result, "nlp_score", 0) if nlp_result else 0,
        "rvol":              _parse_float(td.get("rvol"), 1.0),
        "vwap_position":     _parse_float(td.get("vwap_position")),
        "hold_time_min":     _parse_float(td.get("hold_time_min")),
        "entry_hour":        _parse_float(td.get("entry_hour"), 10),
        "day_of_week":       _parse_float(td.get("day_of_week"), 2),
        "score_band":        0 if score < 75 else (1 if score < 85 else 2),
    }
    return features


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("PMO ML Engine — smoke test\n")

    random.seed(42)

    # Generate synthetic trade history
    def make_synthetic_trades(n=50):
        trades = []
        for i in range(n):
            score = random.uniform(65, 92)
            rvol  = random.uniform(0.8, 4.0)
            # Higher score = worse (inverted model!) but RVOL helps
            base_win_prob = 0.65 - (score - 65) / 90 * 0.4 + (rvol - 1.0) * 0.08
            won = 1 if random.random() < base_win_prob else 0
            pnl = random.uniform(0.5, 3.0) if won else random.uniform(-2.0, -0.3)
            trades.append({
                "score":             round(score, 1),
                "rvol":              round(rvol, 2),
                "pnl":               round(pnl, 2),
                "pattern_score_mod": random.choice([-4, 0, 0, 6, 8]),
                "sentiment_score":   random.randint(-40, 60),
                "nlp_score":         random.randint(-30, 50),
                "vwap_position":     round(random.uniform(-2, 3), 2),
                "hold_time_min":     random.randint(15, 390),
                "entry_time":        f"2026-01-{(i%20)+1:02d} {random.randint(9,14):02d}:{random.randint(0,59):02d}:00",
            })
        return trades

    engine = MLEngine()
    trades = make_synthetic_trades(50)
    success = engine.train(trades)

    print(f"Training result: {success} | Trades: {engine.training_trades}")
    print()

    # Predict for a few candidate setups
    test_cases = [
        {"name": "Strong setup",   "pmo_score": 70, "rvol": 2.8, "pattern_score_mod": 6,  "sentiment_score": 40},
        {"name": "Weak setup",     "pmo_score": 85, "rvol": 0.9, "pattern_score_mod": -4, "sentiment_score": -20},
        {"name": "Neutral setup",  "pmo_score": 77, "rvol": 1.5, "pattern_score_mod": 0,  "sentiment_score": 0},
    ]

    for tc in test_cases:
        name = tc.pop("name")
        result = engine.predict(tc)
        print(f"{name}:")
        print(f"  {result}")
        print(f"  Journal: {result.get_journal_dict()}")
        if result.warning:
            print(f"  WARN: {result.warning}")
        print()

    # Feature importance
    print("Feature importance (top 5):")
    fi = sorted(engine._feature_importances.items(), key=lambda x: x[1], reverse=True)
    for feat, imp in fi[:5]:
        print(f"  {feat:<22} {imp:.4f}")

    print("\nSmoke test complete.")
