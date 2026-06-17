from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("pmo.data_collection")

DEFAULT_TIMEOUT_MINUTES = 120
DEFAULT_MAX_TRADES = 20

NORMAL_GATE_LABELS = {
    "min_score": 65.0,
    "min_rvol": 2.0,
    "open_from": "09:40",
    "gap_required": True,
    "orb_required": True,
    "regime_allowed": "BULL",
    "max_trades_day": 10,
}

DATA_COLLECTION_GATES = {
    "PMO_EXECUTOR_MIN_SCORE": 60.0,
    "PMO_PAPER_EXECUTOR_MIN_SCORE": 60.0,
    "PMO_BACKGROUND_PAPER_MIN_SCORE": 60.0,
    "PMO_WHY_NOT_MIN_SCORE": 60.0,
    "PMO_SCORE_WATCH_ALERT_MIN": 60.0,
    "PMO_SCORE_PAPER_ONLY_MIN": 60.0,
    "PMO_SCORE_PRIORITY_PAPER_MIN": 70.0,
    "PMO_SCORE_ELITE_PAPER_MIN": 85.0,
    "PMO_REBUILD_ENTRY_SCORE_MIN": 60.0,
    "PMO_REBUILD_ENTRY_SCORE_MAX": 100.0,
    "PMO_REBUILD_SUSPEND_ABOVE_SCORE": 101.0,
    "PMO_WHY_NOT_MIN_RVOL": 1.2,
    "PMO_OPENING_MIN_RVOL": 1.2,
    "PMO_TICK_TIMING_MIN_RVOL": 1.2,
    "PMO_OPENING_EARLIEST_ENTRY": "09:35",
    "PMO_OPENING_REQUIRE_GAP_UP_HOLD": False,
    "PMO_OPENING_ALLOWED_GAP_SIGNALS": ["GAP_UP_HOLD", "GAP_UP", "FLAT", "NO_GAP"],
    "PMO_OPENING_REQUIRE_ORB_BREAKOUT": False,
    "PMO_OPENING_BLOCK_ON_MISSING_EDGE": False,
    "PMO_PAPER_MAX_DAILY_TRADES": 20,
    "PMO_PAPER_MAX_STOCK_TRADES": 20,
    "PMO_MAX_DAILY_TRADES": 20,
    "PMO_ORDER_NOTIONAL_USD": 40.0,
    "PMO_MAX_ORDER_NOTIONAL_USD": 40.0,
    "PMO_REGIME_LONG_ALLOWED_VALUES": ["BULL", "BULLISH", "MIXED"],
    "DATA_COLLECTION_ACTIVE": True,
}

ALWAYS_ENFORCED = {
    "ALPACA_PAPER": True,
    "PMO_LIVE_TRADING_ENABLED": False,
    "PMO_ALLOW_LIVE_TRADING": False,
    "PMO_BLOCK_SHORT_SELL_ORDERS": True,
}


@dataclass
class DataCollectionState:
    enabled: bool = False
    enabled_at: Optional[float] = None
    enabled_by: str = ""
    timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES
    max_trades: int = DEFAULT_MAX_TRADES
    trades_collected: int = 0
    auto_disabled_at: Optional[float] = None
    auto_disable_reason: str = ""
    session_id: str = ""

    @property
    def is_active(self) -> bool:
        if not self.enabled or self.enabled_at is None:
            return False
        if time.time() - self.enabled_at > self.timeout_minutes * 60:
            return False
        if self.trades_collected >= self.max_trades:
            return False
        return True

    @property
    def minutes_remaining(self) -> Optional[float]:
        if not self.enabled or self.enabled_at is None:
            return None
        elapsed = (time.time() - self.enabled_at) / 60
        return max(0.0, self.timeout_minutes - elapsed)

    @property
    def trades_remaining(self) -> int:
        return max(0, self.max_trades - self.trades_collected)

    def as_dict(self) -> Dict[str, Any]:
        remaining = self.minutes_remaining
        return {
            "enabled": self.enabled,
            "active": self.is_active,
            "enabled_by": self.enabled_by,
            "enabled_at": self.enabled_at,
            "trades_collected": self.trades_collected,
            "trades_remaining": self.trades_remaining,
            "minutes_remaining": round(remaining, 1) if remaining is not None else None,
            "timeout_minutes": self.timeout_minutes,
            "max_trades": self.max_trades,
            "session_id": self.session_id,
            "auto_disabled_at": self.auto_disabled_at,
            "auto_disable_reason": self.auto_disable_reason,
        }


class DataCollectionManager:
    def __init__(self) -> None:
        self._state = DataCollectionState()

    @property
    def is_active(self) -> bool:
        active = self._state.is_active
        if self._state.enabled and not active:
            self._auto_disable()
        return active

    @property
    def state(self) -> DataCollectionState:
        self.is_active
        return self._state

    def enable(
        self,
        timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES,
        max_trades: int = DEFAULT_MAX_TRADES,
        enabled_by: str = "owner",
    ) -> Dict[str, Any]:
        timeout_minutes = int(max(15, min(240, timeout_minutes)))
        max_trades = int(max(5, min(50, max_trades)))
        self._state = DataCollectionState(
            enabled=True,
            enabled_at=time.time(),
            enabled_by=enabled_by,
            timeout_minutes=timeout_minutes,
            max_trades=max_trades,
            trades_collected=0,
            session_id=uuid.uuid4().hex[:8].upper(),
        )
        logger.warning(
            "DATA COLLECTION MODE ENABLED | session=%s timeout=%dm max=%d trades",
            self._state.session_id,
            timeout_minutes,
            max_trades,
        )
        return {
            "ok": True,
            "enabled": True,
            "session_id": self._state.session_id,
            "message": (
                f"Data collection mode ON for up to {max_trades} paper trades "
                f"or {timeout_minutes} minutes. Live trading stays locked."
            ),
            "status": self.get_status()["data_collection"],
        }

    def disable(self, reason: str = "manual") -> Dict[str, Any]:
        collected = self._state.trades_collected
        session = self._state.session_id
        self._state.enabled = False
        logger.warning(
            "DATA COLLECTION MODE DISABLED | reason=%s session=%s collected=%d",
            reason,
            session,
            collected,
        )
        return {
            "ok": True,
            "enabled": False,
            "reason": reason,
            "trades_collected": collected,
            "session_id": session,
            "message": f"Data collection mode OFF. Collected {collected} paper trades. Normal gates restored.",
            "status": self.get_status()["data_collection"],
        }

    def _auto_disable(self) -> None:
        if not self._state.enabled:
            return
        elapsed = ((time.time() - self._state.enabled_at) / 60) if self._state.enabled_at else 0
        if elapsed > self._state.timeout_minutes:
            reason = f"timeout ({self._state.timeout_minutes}min elapsed)"
        else:
            reason = f"trade limit reached ({self._state.trades_collected} trades)"
        self._state.enabled = False
        self._state.auto_disabled_at = time.time()
        self._state.auto_disable_reason = reason
        logger.warning("DATA COLLECTION MODE AUTO-DISABLED | reason=%s", reason)

    def record_trade(self, ticker: str = "") -> int:
        if not self._state.enabled:
            return self._state.trades_collected
        self._state.trades_collected += 1
        logger.info(
            "DataCollection: trade #%d recorded (%s) | %d remaining",
            self._state.trades_collected,
            ticker,
            self._state.trades_remaining,
        )
        if self._state.trades_collected >= self._state.max_trades:
            self._auto_disable()
        return self._state.trades_collected

    def apply_to_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        updated = dict(settings or {})
        if not self.is_active:
            updated["DATA_COLLECTION_ACTIVE"] = False
            return updated
        updated.update(DATA_COLLECTION_GATES)
        updated["DATA_COLLECTION_SESSION"] = self._state.session_id
        updated["DATA_COLLECTION_TAG"] = self.get_journal_tag()
        updated.update(ALWAYS_ENFORCED)
        return updated

    def get_journal_tag(self) -> str:
        if self.is_active:
            return f"DATA_COLLECTION_{self._state.session_id}"
        return "NORMAL"

    def get_status(self) -> Dict[str, Any]:
        active_gates = dict(DATA_COLLECTION_GATES)
        active_gates.pop("DATA_COLLECTION_ACTIVE", None)
        return {
            "ok": True,
            "data_collection": {
                **self._state.as_dict(),
                "always_enforced": {
                    "paper_only": True,
                    "live_locked": True,
                    "short_blocked": True,
                    "blocklist_enforced": True,
                },
                "normal_gates": NORMAL_GATE_LABELS,
                "relaxed_gates": {
                    "min_score": 60.0,
                    "min_rvol": 1.2,
                    "open_from": "09:35",
                    "gap_required": False,
                    "gap_allowed": "GAP_UP/GAP_UP_HOLD/FLAT",
                    "orb_required": False,
                    "regime_allowed": "BULL/BULLISH/MIXED",
                    "max_trades_day": self._state.max_trades,
                },
            },
            "current_gates": active_gates if self.is_active else {"DATA_COLLECTION_ACTIVE": False},
            "live_unlocked": False,
            "orders_placed": False,
            "paper_only": True,
            "blocklist_enforced": True,
        }
