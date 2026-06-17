"""
PMO Alpha Decay Profiler.

Ticker-specific read-only profiling from PMO's own journal:
- alpha half-life
- optimal hold window
- move profile
- ticker-specific TP/stop/hold recommendations

This module does not place orders, unlock live trading, or mutate settings.
"""

from __future__ import annotations

import csv
import json
import logging
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("pmo.alpha_decay")

MIN_TRADES_FOR_PROFILE = 3
MIN_TRADES_CONFIDENT = 8


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


def _pnl(row: Dict[str, Any]) -> float:
    for key in ("pnl", "pnl_usd", "profit_loss", "realized_pnl", "return_pct", "pct_gain", "gain_pct", "pnl_pct"):
        value = row.get(key, "")
        if value not in (None, "", "N/A"):
            return _as_float(value, 0.0)
    return 0.0


def _status(row: Dict[str, Any]) -> str:
    return " ".join(str(row.get(key, "") or "").upper() for key in ("outcome", "result", "trade_result", "status"))


def _won(row: Dict[str, Any]) -> bool:
    status = _status(row)
    if "WIN" in status or "PROFIT" in status:
        return True
    if "LOSS" in status or "LOSE" in status:
        return False
    return _pnl(row) > 0


def _closed(row: Dict[str, Any]) -> bool:
    status = _status(row)
    if any(token in status for token in ("CLOSED", "WIN", "LOSS", "COMPLETE")):
        return True
    return _pnl(row) != 0


def _hold_min(row: Dict[str, Any]) -> Optional[float]:
    for key in ("hold_time_min", "hold_minutes", "duration_min", "hold_time", "max_hold_minutes"):
        value = row.get(key, "")
        if value not in (None, "", "N/A"):
            return _as_float(value, 0.0)
    return None


def _ticker(row: Dict[str, Any]) -> str:
    return str(row.get("ticker") or row.get("symbol") or "").upper().strip()


@dataclass
class TickerProfile:
    ticker: str
    trade_count: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    alpha_half_life_min: Optional[float] = None
    optimal_hold_min: Optional[float] = None
    avg_hold_winners_min: Optional[float] = None
    avg_hold_losers_min: Optional[float] = None
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    move_profile: str = "UNKNOWN"
    recommended_tp_pct: Optional[float] = None
    recommended_stop_pct: Optional[float] = None
    recommended_hold_min: Optional[int] = None
    confidence: str = "LOW"
    volatility_score: float = 0.0
    momentum_persistence: float = 0.0

    def get_journal_dict(self) -> Dict[str, Any]:
        return {
            "decay_ticker": self.ticker,
            "decay_half_life": self.alpha_half_life_min,
            "decay_optimal_hold": self.optimal_hold_min,
            "decay_profile": self.move_profile,
            "decay_rec_tp": self.recommended_tp_pct,
            "decay_rec_stop": self.recommended_stop_pct,
            "decay_confidence": self.confidence,
        }

    def get_dashboard_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "trades": self.trade_count,
            "wins": self.win_count,
            "losses": self.loss_count,
            "wr": round(self.win_rate * 100, 1),
            "half_life": self.alpha_half_life_min,
            "optimal_hold": self.optimal_hold_min,
            "profile": self.move_profile,
            "rec_tp": self.recommended_tp_pct,
            "rec_stop": self.recommended_stop_pct,
            "rec_hold": self.recommended_hold_min,
            "confidence": self.confidence,
            "vol_score": round(self.volatility_score, 3),
            "momentum": round(self.momentum_persistence, 3),
        }

    def __str__(self) -> str:
        return (
            f"{self.ticker}: {self.move_profile} | WR={self.win_rate * 100:.0f}% "
            f"n={self.trade_count} | half-life={self.alpha_half_life_min}min | "
            f"rec TP={self.recommended_tp_pct}% stop={self.recommended_stop_pct}% | conf={self.confidence}"
        )


class AlphaDecayProfiler:
    def __init__(
        self,
        blocklist: Optional[set[str]] = None,
        default_tp: float = 6.0,
        default_stop: float = 4.0,
        default_hold: int = 90,
        min_trades: int = MIN_TRADES_FOR_PROFILE,
        confident_trades: int = MIN_TRADES_CONFIDENT,
    ):
        self._blocklist = {str(item).upper() for item in (blocklist or {"HOOD", "PSQ", "RWM", "CVX"})}
        self._default_tp = default_tp
        self._default_stop = default_stop
        self._default_hold = default_hold
        self._min_trades = max(1, int(min_trades))
        self._confident_trades = max(self._min_trades, int(confident_trades))
        self._rows: List[Dict[str, Any]] = []
        self._profiles: Dict[str, TickerProfile] = {}

    def load(self, source: Any) -> int:
        if isinstance(source, (str, Path)):
            path = Path(source)
            if not path.exists():
                logger.warning("AlphaDecay: file not found: %s", source)
                self._rows = []
                self._profiles = {}
                return 0
            with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
                rows = list(csv.DictReader(handle))
        else:
            rows = list(source or [])

        closed: List[Dict[str, Any]] = []
        for row in rows:
            ticker = _ticker(row)
            if not ticker or ticker == "SYSTEM" or ticker in self._blocklist:
                continue
            if _closed(row):
                closed.append(dict(row))

        self._rows = closed
        self._profiles = {}
        logger.info("AlphaDecay: loaded %d closed trades", len(closed))
        return len(closed)

    def _classify_move_profile(
        self,
        avg_hold_win: Optional[float],
        avg_hold_loss: Optional[float],
        win_rate: float,
        avg_win_pct: float,
        avg_loss_pct: float,
    ) -> tuple[str, float, float]:
        if avg_hold_win is None:
            return "UNKNOWN", 0.5, 0.5

        if avg_hold_loss and avg_hold_win:
            momentum = min(1.0, (avg_hold_win / max(avg_hold_loss, 1.0)) / 2.0)
        else:
            momentum = 0.5

        vol_score = abs(avg_win_pct) / max(abs(avg_loss_pct), 0.01) if avg_loss_pct != 0 else 1.0

        if win_rate >= 0.60 and avg_hold_win <= 20:
            profile = "FAST_BURST"
        elif win_rate >= 0.55 and avg_hold_win >= 45:
            profile = "SLOW_GRIND"
        elif win_rate < 0.40 and avg_hold_loss and avg_hold_loss < avg_hold_win:
            profile = "MEAN_REVERT"
        elif vol_score > 2.0:
            profile = "VOLATILE"
        else:
            profile = "BALANCED"

        return profile, round(momentum, 3), round(vol_score, 3)

    def _compute_alpha_half_life(self, avg_hold_win: Optional[float], move_profile: str) -> Optional[float]:
        if avg_hold_win is None:
            return None
        decay_factors = {
            "FAST_BURST": 0.4,
            "SLOW_GRIND": 0.6,
            "MEAN_REVERT": 0.3,
            "VOLATILE": 0.5,
            "BALANCED": 0.5,
            "UNKNOWN": 0.5,
        }
        return round(avg_hold_win * decay_factors.get(move_profile, 0.5), 0)

    def _compute_recommended_params(
        self,
        move_profile: str,
        avg_win_pct: float,
        avg_loss_pct: float,
        optimal_hold: Optional[float],
    ) -> tuple[float, float, int]:
        if abs(avg_win_pct) > 0.1:
            rec_tp = max(3.0, min(15.0, round(abs(avg_win_pct) * 1.15, 1)))
        else:
            rec_tp = self._default_tp

        if abs(avg_loss_pct) > 0.1:
            rec_stop = max(2.0, min(8.0, round(abs(avg_loss_pct) * 0.85, 1)))
        else:
            rec_stop = self._default_stop

        if move_profile == "FAST_BURST":
            rec_tp = min(rec_tp, 5.0)
            rec_stop = min(rec_stop, 3.0)
        elif move_profile == "SLOW_GRIND":
            rec_tp = max(rec_tp, 7.0)
            rec_stop = max(rec_stop, 4.0)
        elif move_profile == "MEAN_REVERT":
            rec_tp = min(rec_tp, 3.0)
            rec_stop = min(rec_stop, 2.5)
        elif move_profile == "VOLATILE":
            rec_stop = max(rec_stop, 5.0)

        return round(rec_tp, 1), round(rec_stop, 1), int(optimal_hold) if optimal_hold else self._default_hold

    def build_profile(self, ticker: str) -> Optional[TickerProfile]:
        clean = str(ticker or "").upper().strip()
        rows = [row for row in self._rows if _ticker(row) == clean]
        trade_count = len(rows)
        if trade_count < self._min_trades:
            return None

        wins = [row for row in rows if _won(row)]
        losses = [row for row in rows if not _won(row)]
        win_rate = len(wins) / trade_count if trade_count else 0.0
        win_pnls = [_pnl(row) for row in wins]
        loss_pnls = [_pnl(row) for row in losses]
        avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
        avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0

        win_holds = [value for value in (_hold_min(row) for row in wins) if value is not None]
        loss_holds = [value for value in (_hold_min(row) for row in losses) if value is not None]
        all_holds = [value for value in (_hold_min(row) for row in rows) if value is not None]

        avg_hold_win = sum(win_holds) / len(win_holds) if win_holds else None
        avg_hold_loss = sum(loss_holds) / len(loss_holds) if loss_holds else None
        avg_hold_all = sum(all_holds) / len(all_holds) if all_holds else None

        if avg_hold_win and avg_hold_loss:
            optimal_hold = avg_hold_win * 1.1 if avg_hold_win < avg_hold_loss else avg_hold_win * 0.9
        elif avg_hold_win:
            optimal_hold = avg_hold_win
        else:
            optimal_hold = avg_hold_all

        profile, momentum, vol_score = self._classify_move_profile(avg_hold_win, avg_hold_loss, win_rate, avg_win, avg_loss)
        half_life = self._compute_alpha_half_life(avg_hold_win, profile)
        rec_tp, rec_stop, rec_hold = self._compute_recommended_params(profile, avg_win, avg_loss, optimal_hold)
        confidence = "HIGH" if trade_count >= self._confident_trades else "MEDIUM" if trade_count >= self._min_trades * 2 else "LOW"

        return TickerProfile(
            ticker=clean,
            trade_count=trade_count,
            win_count=len(wins),
            loss_count=len(losses),
            win_rate=round(win_rate, 4),
            alpha_half_life_min=half_life,
            optimal_hold_min=round(optimal_hold, 0) if optimal_hold else None,
            avg_hold_winners_min=round(avg_hold_win, 1) if avg_hold_win else None,
            avg_hold_losers_min=round(avg_hold_loss, 1) if avg_hold_loss else None,
            avg_win_pct=round(avg_win, 3),
            avg_loss_pct=round(avg_loss, 3),
            move_profile=profile,
            recommended_tp_pct=rec_tp,
            recommended_stop_pct=rec_stop,
            recommended_hold_min=rec_hold,
            confidence=confidence,
            volatility_score=vol_score,
            momentum_persistence=momentum,
        )

    def build_all_profiles(self) -> Dict[str, TickerProfile]:
        profiles: Dict[str, TickerProfile] = {}
        for ticker in sorted({_ticker(row) for row in self._rows if _ticker(row)}):
            profile = self.build_profile(ticker)
            if profile:
                profiles[ticker] = profile
                logger.info("AlphaDecay: %s", profile)
        self._profiles = profiles
        return profiles

    def get_profile(self, ticker: str) -> Optional[TickerProfile]:
        clean = str(ticker or "").upper().strip()
        if clean not in self._profiles:
            profile = self.build_profile(clean)
            if profile:
                self._profiles[clean] = profile
        return self._profiles.get(clean)

    def get_optimal_params(self, ticker: str, min_confidence: str = "MEDIUM") -> Dict[str, Any]:
        ranks = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
        profile = self.get_profile(ticker)
        min_rank = ranks.get(str(min_confidence or "MEDIUM").upper(), 2)
        if profile and ranks.get(profile.confidence, 0) >= min_rank:
            return {
                "tp_pct": profile.recommended_tp_pct,
                "stop_pct": profile.recommended_stop_pct,
                "hold_min": profile.recommended_hold_min,
                "profile": profile.move_profile,
                "half_life": profile.alpha_half_life_min,
                "source": "TICKER_PROFILE",
                "confidence": profile.confidence,
            }
        return {
            "tp_pct": self._default_tp,
            "stop_pct": self._default_stop,
            "hold_min": self._default_hold,
            "profile": "DEFAULT",
            "half_life": None,
            "source": "DEFAULT",
            "confidence": "NONE",
        }

    def summary_report(self) -> Dict[str, Any]:
        if not self._profiles:
            self.build_all_profiles()

        by_profile: Dict[str, List[TickerProfile]] = defaultdict(list)
        for profile in self._profiles.values():
            by_profile[profile.move_profile].append(profile)

        return {
            "ok": True,
            "total_tickers_profiled": len(self._profiles),
            "total_trades_analyzed": len(self._rows),
            "profiles_by_type": {
                key: [
                    {
                        "ticker": profile.ticker,
                        "wr": round(profile.win_rate * 100, 1),
                        "n": profile.trade_count,
                        "rec_tp": profile.recommended_tp_pct,
                        "rec_stop": profile.recommended_stop_pct,
                        "confidence": profile.confidence,
                    }
                    for profile in values
                ]
                for key, values in by_profile.items()
            },
            "top_tickers": sorted(
                [profile.get_dashboard_dict() for profile in self._profiles.values()],
                key=lambda row: (row["wr"], row["trades"]),
                reverse=True,
            )[:20],
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    random.seed(42)
    journal: List[Dict[str, Any]] = []
    for index in range(12):
        won = random.random() < 0.65
        pnl = random.uniform(1.0, 2.5) if won else random.uniform(-1.8, -0.4)
        hold = random.uniform(8, 18) if won else random.uniform(25, 45)
        journal.append({"ticker": "NVDA", "pnl": round(pnl, 2), "status": "CLOSED_WIN" if won else "CLOSED_LOSS", "hold_time_min": round(hold, 0)})
    for index in range(10):
        won = random.random() < 0.45
        pnl = random.uniform(2.0, 4.0) if won else random.uniform(-1.2, -0.3)
        hold = random.uniform(35, 60) if won else random.uniform(5, 15)
        journal.append({"ticker": "TSLA", "pnl": round(pnl, 2), "status": "CLOSED_WIN" if won else "CLOSED_LOSS", "hold_time_min": round(hold, 0)})
    for index in range(8):
        won = random.random() < 0.62
        pnl = random.uniform(0.8, 1.8) if won else random.uniform(-1.0, -0.3)
        hold = random.uniform(45, 90) if won else random.uniform(20, 40)
        journal.append({"ticker": "AAPL", "pnl": round(pnl, 2), "status": "CLOSED_WIN" if won else "CLOSED_LOSS", "hold_time_min": round(hold, 0)})

    profiler = AlphaDecayProfiler()
    profiler.load(journal)
    profiler.build_all_profiles()
    print(json.dumps(profiler.summary_report(), indent=2))
