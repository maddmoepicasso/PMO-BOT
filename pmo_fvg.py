"""
PMO Fair Value Gap detector.

This module is intentionally self-contained and read-only. It detects
three-candle fair value gaps from OHLCV bars and returns serializable
metadata for PMO scoring, journals, chart overlays, and research reports.
"""

from __future__ import annotations

import datetime as _datetime
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("pmo.fvg")

MIN_GAP_PCT = 0.10
FVG_ZONE_PROXIMITY_PCT = 0.50
FVG_SCORE_MODIFIER = 5
FVG_AGAINST_MODIFIER = -3


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clean_direction(value: Any) -> str:
    text = str(value or "long").strip().lower()
    if text in {"short", "sell", "put", "put_bias", "bearish"}:
        return "short"
    return "long"


@dataclass
class FVGZone:
    """One detected fair value gap zone."""

    kind: str
    gap_high: float
    gap_low: float
    gap_size: float
    gap_pct: float
    bar_index: int
    mitigated: bool = False

    @property
    def midpoint(self) -> float:
        return (self.gap_high + self.gap_low) / 2.0

    def price_in_zone(self, price: float, proximity_pct: float = FVG_ZONE_PROXIMITY_PCT) -> bool:
        buffer = self.midpoint * max(0.0, proximity_pct) / 100.0
        return (self.gap_low - buffer) <= price <= (self.gap_high + buffer)

    def as_dict(self, current_price: Optional[float] = None, proximity_pct: float = FVG_ZONE_PROXIMITY_PCT) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "gap_high": round(self.gap_high, 4),
            "gap_low": round(self.gap_low, 4),
            "midpoint": round(self.midpoint, 4),
            "gap_size": round(self.gap_size, 4),
            "gap_pct": round(self.gap_pct, 3),
            "bar_index": self.bar_index,
            "mitigated": bool(self.mitigated),
            "active": not self.mitigated,
            "price_in_zone": bool(self.price_in_zone(current_price, proximity_pct)) if current_price else False,
        }

    def __str__(self) -> str:
        state = "MITIGATED" if self.mitigated else "ACTIVE"
        return f"FVG {self.kind.upper()} {self.gap_low:.4g}-{self.gap_high:.4g} ({self.gap_pct:.3f}%) {state}"


@dataclass
class FVGResult:
    """Serializable result from FVG detection."""

    fvg_found: bool = False
    active_fvgs: List[FVGZone] = field(default_factory=list)
    nearest_fvg: Optional[FVGZone] = None
    price_in_fvg: bool = False
    fvg_signal: str = "NONE"
    fvg_confluence: str = "NONE"
    score_modifier: int = 0
    current_price: Optional[float] = None
    total_fvgs_found: int = 0
    mitigated_count: int = 0

    def get_journal_dict(self) -> Dict[str, Any]:
        nearest = self.nearest_fvg
        return {
            "fvg_found": bool(self.fvg_found),
            "fvg_signal": self.fvg_signal,
            "fvg_confluence": self.fvg_confluence,
            "fvg_score_mod": self.score_modifier,
            "fvg_gap_low": round(nearest.gap_low, 4) if nearest else "",
            "fvg_gap_high": round(nearest.gap_high, 4) if nearest else "",
            "fvg_gap_pct": round(nearest.gap_pct, 3) if nearest else "",
            "fvg_price_in_zone": bool(self.price_in_fvg),
            "fvg_total_active": max(0, self.total_fvgs_found - self.mitigated_count),
        }

    def get_dashboard_dict(self) -> Dict[str, Any]:
        zones = [
            zone.as_dict(self.current_price)
            for zone in self.active_fvgs[-5:]
        ]
        data = self.get_journal_dict()
        data.update({
            "found": bool(self.fvg_found),
            "signal": self.fvg_signal,
            "confluence": self.fvg_confluence,
            "score_mod": self.score_modifier,
            "in_zone": bool(self.price_in_fvg),
            "price": round(self.current_price, 4) if self.current_price else "",
            "zones": zones,
        })
        return data

    def __str__(self) -> str:
        if not self.fvg_found:
            return "FVG: none detected"
        zone_note = " price_in_zone" if self.price_in_fvg else ""
        return (
            f"FVG: {self.fvg_signal} confluence={self.fvg_confluence} "
            f"mod={self.score_modifier:+d} active={max(0, self.total_fvgs_found - self.mitigated_count)}{zone_note}"
        )


class FVGDetector:
    """Detects bullish and bearish fair value gaps in OHLCV bars."""

    def __init__(
        self,
        min_gap_pct: float = MIN_GAP_PCT,
        zone_proximity_pct: float = FVG_ZONE_PROXIMITY_PCT,
        lookback: int = 50,
        score_modifier: int = FVG_SCORE_MODIFIER,
        against_modifier: int = FVG_AGAINST_MODIFIER,
    ) -> None:
        self.min_gap_pct = max(0.0, _to_float(min_gap_pct, MIN_GAP_PCT))
        self.zone_proximity_pct = max(0.0, _to_float(zone_proximity_pct, FVG_ZONE_PROXIMITY_PCT))
        self.lookback = max(3, int(_to_float(lookback, 50)))
        self.score_modifier = int(_to_float(score_modifier, FVG_SCORE_MODIFIER))
        self.against_modifier = int(_to_float(against_modifier, FVG_AGAINST_MODIFIER))

    def _detect_fvgs(self, bars: List[Dict[str, Any]]) -> List[FVGZone]:
        fvgs: List[FVGZone] = []
        scan_bars = bars[-self.lookback:] if len(bars) > self.lookback else bars
        offset = max(0, len(bars) - self.lookback)

        for idx in range(1, len(scan_bars) - 1):
            c1 = scan_bars[idx - 1]
            c3 = scan_bars[idx + 1]
            high1 = _to_float(c1.get("high") or c1.get("h"), 0)
            low1 = _to_float(c1.get("low") or c1.get("l"), 0)
            high3 = _to_float(c3.get("high") or c3.get("h"), 0)
            low3 = _to_float(c3.get("low") or c3.get("l"), 0)
            if min(high1, low1, high3, low3) <= 0:
                continue

            if high1 < low3:
                gap_low = high1
                gap_high = low3
                gap_size = gap_high - gap_low
                gap_pct = gap_size / gap_low * 100.0 if gap_low else 0.0
                if gap_pct >= self.min_gap_pct:
                    fvgs.append(FVGZone("bullish", gap_high, gap_low, gap_size, gap_pct, offset + idx))
            elif low1 > high3:
                gap_low = high3
                gap_high = low1
                gap_size = gap_high - gap_low
                gap_pct = gap_size / gap_high * 100.0 if gap_high else 0.0
                if gap_pct >= self.min_gap_pct:
                    fvgs.append(FVGZone("bearish", gap_high, gap_low, gap_size, gap_pct, offset + idx))
        return fvgs

    def _check_mitigation(self, fvgs: List[FVGZone], bars: List[Dict[str, Any]]) -> List[FVGZone]:
        for fvg in fvgs:
            subsequent = bars[fvg.bar_index + 2:]
            for bar in subsequent:
                low = _to_float(bar.get("low") or bar.get("l"), 0)
                high = _to_float(bar.get("high") or bar.get("h"), 0)
                if fvg.kind == "bullish" and low <= fvg.gap_low:
                    fvg.mitigated = True
                    break
                if fvg.kind == "bearish" and high >= fvg.gap_high:
                    fvg.mitigated = True
                    break
        return fvgs

    def detect(self, bars: Iterable[Dict[str, Any]], trade_direction: str = "long") -> FVGResult:
        clean_bars = [row for row in bars or [] if isinstance(row, dict)]
        if len(clean_bars) < 3:
            return FVGResult()
        current_price = _to_float(clean_bars[-1].get("close") or clean_bars[-1].get("c"), 0)
        if current_price <= 0:
            return FVGResult()

        all_fvgs = self._check_mitigation(self._detect_fvgs(clean_bars), clean_bars)
        active = [item for item in all_fvgs if not item.mitigated]
        mitigated_count = len(all_fvgs) - len(active)
        if not active:
            return FVGResult(
                fvg_found=False,
                current_price=current_price,
                total_fvgs_found=len(all_fvgs),
                mitigated_count=mitigated_count,
            )

        nearest = min(active, key=lambda item: abs(current_price - item.midpoint))
        in_zone = nearest.price_in_zone(current_price, self.zone_proximity_pct)
        signal = nearest.kind.upper()
        direction = _clean_direction(trade_direction)
        if (signal == "BULLISH" and direction == "long") or (signal == "BEARISH" and direction == "short"):
            confluence = "ALIGNED"
            modifier = self.score_modifier if in_zone else max(0, self.score_modifier - 2)
        elif (signal == "BULLISH" and direction == "short") or (signal == "BEARISH" and direction == "long"):
            confluence = "AGAINST"
            modifier = self.against_modifier
        else:
            confluence = "NONE"
            modifier = 0

        result = FVGResult(
            fvg_found=True,
            active_fvgs=active,
            nearest_fvg=nearest,
            price_in_fvg=in_zone,
            fvg_signal=signal,
            fvg_confluence=confluence,
            score_modifier=int(modifier),
            current_price=current_price,
            total_fvgs_found=len(all_fvgs),
            mitigated_count=mitigated_count,
        )
        logger.info("FVGDetector: %s", result)
        return result


def add_fvg_to_pattern_engine(
    pattern_engine_instance: Any,
    bars: List[Dict[str, Any]],
    trade_direction: str = "long",
    detector: Optional[FVGDetector] = None,
    combined_cap: int = 12,
) -> Tuple[Any, FVGResult, int]:
    """Return pattern result, FVG result, and capped combined modifier."""
    detector = detector or FVGDetector()
    pattern_result = pattern_engine_instance.detect(bars, trade_direction)
    fvg_result = detector.detect(bars, trade_direction)
    pattern_mod = int(_to_float(getattr(pattern_result, "score_modifier", 0), 0))
    combined = pattern_mod + int(_to_float(fvg_result.score_modifier, 0))
    cap = max(0, int(_to_float(combined_cap, 12)))
    if cap:
        combined = max(-cap, min(cap, combined))
    return pattern_result, fvg_result, combined


FVG_JOURNAL_COLUMNS = [
    "fvg_found",
    "fvg_signal",
    "fvg_confluence",
    "fvg_score_mod",
    "fvg_gap_low",
    "fvg_gap_high",
    "fvg_gap_pct",
    "fvg_price_in_zone",
    "fvg_total_active",
]


def _make_test_bars(bullish: bool = True) -> List[Dict[str, Any]]:
    random.seed(42)
    bars: List[Dict[str, Any]] = []
    ts = _datetime.datetime(2026, 6, 16, 9, 30)
    price = 100.0
    for _ in range(20):
        open_price = price
        close_price = price + random.gauss(0, 0.2)
        bars.append({
            "datetime": ts.isoformat(),
            "open": round(open_price, 2),
            "high": round(max(open_price, close_price) + 0.1, 2),
            "low": round(min(open_price, close_price) - 0.1, 2),
            "close": round(close_price, 2),
        })
        price = close_price
        ts += _datetime.timedelta(minutes=5)

    if bullish:
        bars.extend([
            {"datetime": ts.isoformat(), "open": price, "high": price + 0.30, "low": price - 0.10, "close": price + 0.20},
            {"datetime": (ts + _datetime.timedelta(minutes=5)).isoformat(), "open": price + 0.20, "high": price + 1.80, "low": price + 0.20, "close": price + 1.60},
            {"datetime": (ts + _datetime.timedelta(minutes=10)).isoformat(), "open": price + 1.60, "high": price + 2.00, "low": price + 0.80, "close": price + 0.95},
        ])
    else:
        bars.extend([
            {"datetime": ts.isoformat(), "open": price, "high": price + 0.10, "low": price - 0.30, "close": price - 0.20},
            {"datetime": (ts + _datetime.timedelta(minutes=5)).isoformat(), "open": price - 0.20, "high": price - 0.20, "low": price - 1.80, "close": price - 1.60},
            {"datetime": (ts + _datetime.timedelta(minutes=10)).isoformat(), "open": price - 1.60, "high": price - 0.80, "low": price - 2.00, "close": price - 0.95},
        ])
    return bars


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    detector = FVGDetector()
    bullish = detector.detect(_make_test_bars(True), "long")
    bearish = detector.detect(_make_test_bars(False), "short")
    against = detector.detect(_make_test_bars(False), "long")
    print("PMO FVG Detector smoke test")
    print(bullish)
    print(bullish.get_journal_dict())
    print(bearish)
    print(bearish.get_journal_dict())
    print(against)
    print(against.get_journal_dict())
