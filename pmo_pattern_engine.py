"""
PMO Pattern Engine — pmo_pattern_engine.py
==========================================
Zigzag-based chart pattern detector for PMO Bot.
Matches the full pattern set from theUltimator5 "Pattern Detector" (TradingView).

Detected patterns (20 total):
  Continuation: Bull Flag, Bear Flag, Bull Pennant, Bear Pennant,
                Ascending Triangle, Descending Triangle, Symmetrical Triangle,
                Rising Wedge, Falling Wedge, Bull Channel, Bear Channel
  Reversal:     Double Top, Double Bottom, Head & Shoulders, Inverse H&S,
                Triple Top, Triple Bottom, Broadening Top, Broadening Bottom,
                Cup & Handle

Usage:
    from pmo_pattern_engine import PatternEngine
    engine = PatternEngine()
    result = engine.detect(bars)   # bars = list of dicts with OHLCV + datetime
    # result: PatternResult(name, direction, confidence, pivots, score_modifier)

Integration with pmo_bot.py:
    Call detect() after intraday bars are refreshed (post 5m bar update).
    Pass result to get_score_modifier() for the PMO score v2 adjustment.
    Log result to trade journal via get_journal_dict().
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
import math

logger = logging.getLogger("pmo.pattern_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Zigzag settings (mirroring Pine Script defaults from theUltimator5)
ZIGZAG_DEPTH = 10       # minimum bars between pivots
ZIGZAG_DEVIATION = 5.0  # minimum % move to qualify as a swing

# Tolerance for geometry matching (% of price)
TOLERANCE = 0.03        # 3% tolerance for "equal" highs/lows

# Score modifiers applied to PMO score v2
# Direction-aware: bullish pattern on long = positive, on short = negative
SCORE_MODIFIERS = {
    # (pattern_direction, trade_direction) -> modifier
    ("bullish",  "long"):  +6,
    ("bullish",  "short"): -4,
    ("bearish",  "long"):  -4,
    ("bearish",  "short"): +6,
    ("neutral",  "long"):   0,
    ("neutral",  "short"):  0,
    # High-conviction patterns get extra weight
    ("bullish_strong",  "long"):  +8,
    ("bullish_strong",  "short"): -5,
    ("bearish_strong",  "long"):  -6,
    ("bearish_strong",  "short"): +6,
}

# Pattern catalogue: name → direction bucket
PATTERN_DIRECTIONS = {
    "Bull Flag":            "bullish",
    "Bear Flag":            "bearish",
    "Bull Pennant":         "bullish",
    "Bear Pennant":         "bearish",
    "Ascending Triangle":   "bullish",
    "Descending Triangle":  "bearish",
    "Symmetrical Triangle": "neutral",
    "Rising Wedge":         "bearish",   # Rising wedge = bearish reversal/continuation
    "Falling Wedge":        "bullish",   # Falling wedge = bullish
    "Bull Channel":         "bullish",
    "Bear Channel":         "bearish",
    "Double Top":           "bearish_strong",
    "Double Bottom":        "bullish_strong",
    "Head & Shoulders":     "bearish_strong",
    "Inverse H&S":          "bullish_strong",
    "Triple Top":           "bearish_strong",
    "Triple Bottom":        "bullish_strong",
    "Broadening Top":       "bearish",
    "Broadening Bottom":    "bullish",
    "Cup & Handle":         "bullish_strong",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Pivot:
    """A single zigzag pivot point."""
    index: int          # bar index
    price: float        # pivot price
    kind: str           # 'high' or 'low'
    bar_time: object    # datetime of the bar


@dataclass
class PatternResult:
    """Result of a pattern detection run."""
    name: Optional[str] = None          # e.g. "Bull Flag"
    direction: Optional[str] = None     # "bullish" / "bearish" / "neutral" / None
    confidence: float = 0.0             # 0.0–1.0
    pivots: list = field(default_factory=list)  # list of Pivot used to match
    score_modifier: int = 0             # precomputed modifier for the score model
    pattern_found: bool = False
    raw_direction: Optional[str] = None  # e.g. "bullish_strong" before mapping

    def get_journal_dict(self) -> dict:
        """Returns a dict ready to merge into the trade journal row."""
        return {
            "pattern_name":       self.name or "None",
            "pattern_direction":  self.direction or "None",
            "pattern_confidence": round(self.confidence, 3),
            "pattern_score_mod":  self.score_modifier,
        }

    def __str__(self):
        if not self.pattern_found:
            return "No pattern detected"
        return (f"{self.name} ({self.direction}, "
                f"conf={self.confidence:.2f}, mod={self.score_modifier:+d})")


# ---------------------------------------------------------------------------
# Zigzag engine
# ---------------------------------------------------------------------------

class ZigZag:
    """
    Lightweight zigzag implementation.
    Finds alternating swing highs and swing lows in a bar series.
    Mirrors the logic used by most Pine Script zigzag indicators.
    """

    def __init__(self, depth: int = ZIGZAG_DEPTH, deviation: float = ZIGZAG_DEVIATION):
        self.depth = depth
        self.deviation = deviation  # percent

    def compute(self, bars: list) -> list:
        """
        bars: list of dicts with keys: 'high', 'low', 'close', 'datetime'
        Returns: list of Pivot, most recent last.
        """
        if len(bars) < self.depth * 2:
            return []

        pivots = []
        highs = [b["high"] for b in bars]
        lows  = [b["low"]  for b in bars]
        n = len(bars)

        # Find local highs and lows using a rolling window
        candidate_highs = []
        candidate_lows  = []

        for i in range(self.depth, n - self.depth):
            window_high = highs[i - self.depth: i + self.depth + 1]
            window_low  = lows[i  - self.depth: i + self.depth + 1]

            if highs[i] == max(window_high):
                candidate_highs.append((i, highs[i]))
            if lows[i] == min(window_low):
                candidate_lows.append((i, lows[i]))

        # Merge and sort all candidates by index
        all_candidates = (
            [(idx, price, "high") for idx, price in candidate_highs] +
            [(idx, price, "low")  for idx, price in candidate_lows]
        )
        all_candidates.sort(key=lambda x: x[0])

        if not all_candidates:
            return []

        # Build alternating pivot list with deviation filter
        filtered = [all_candidates[0]]
        for idx, price, kind in all_candidates[1:]:
            last = filtered[-1]
            last_price = last[1]
            last_kind  = last[2]

            pct_move = abs(price - last_price) / last_price * 100

            if kind == last_kind:
                # Same type — keep the more extreme one
                if kind == "high" and price > last_price:
                    filtered[-1] = (idx, price, kind)
                elif kind == "low" and price < last_price:
                    filtered[-1] = (idx, price, kind)
            else:
                # Different type — only add if deviation is sufficient
                if pct_move >= self.deviation:
                    filtered.append((idx, price, kind))

        # Convert to Pivot objects
        result = []
        for idx, price, kind in filtered:
            result.append(Pivot(
                index    = idx,
                price    = price,
                kind     = kind,
                bar_time = bars[idx].get("datetime"),
            ))

        return result


# ---------------------------------------------------------------------------
# Pattern matcher
# ---------------------------------------------------------------------------

class PatternMatcher:
    """
    Tests a list of zigzag pivots against each of the 20 pattern templates.
    Uses the most recent N pivots (N depends on pattern complexity).
    """

    def __init__(self, tolerance: float = TOLERANCE):
        self.tol = tolerance

    # ---- Helpers ----

    def _eq(self, a: float, b: float) -> bool:
        """Two prices are 'equal' within tolerance."""
        return abs(a - b) / max(abs(b), 1e-9) <= self.tol

    def _rising(self, *prices) -> bool:
        return all(prices[i] < prices[i+1] for i in range(len(prices)-1))

    def _falling(self, *prices) -> bool:
        return all(prices[i] > prices[i+1] for i in range(len(prices)-1))

    def _converging(self, hi1, hi2, lo1, lo2) -> bool:
        """Highs falling AND lows rising — converging wedge/triangle."""
        return hi2 < hi1 and lo2 > lo1

    def _diverging(self, hi1, hi2, lo1, lo2) -> bool:
        """Highs rising AND lows falling — broadening."""
        return hi2 > hi1 and lo2 < lo1

    def _slope(self, p1: float, p2: float, bars: int) -> float:
        """Price slope per bar."""
        return (p2 - p1) / max(bars, 1)

    def _parallel(self, sl1: float, sl2: float, rtol: float = 0.4) -> bool:
        """Two slopes are roughly parallel."""
        if abs(sl1) < 1e-9 and abs(sl2) < 1e-9:
            return True
        denom = max(abs(sl1), abs(sl2), 1e-9)
        return abs(sl1 - sl2) / denom <= rtol

    def _conf(self, *checks) -> float:
        """Average of bool checks → confidence 0–1."""
        return sum(bool(c) for c in checks) / len(checks)

    # ---- Individual pattern tests ----
    # Each returns (matched: bool, confidence: float)
    # Pivots passed in are already ordered oldest→newest.
    # Convention: H = swing high, L = swing low.

    def test_bull_flag(self, pivots) -> tuple:
        # Need at least 4 pivots: sharp rally (L-H), then consolidation (H-L-H)
        if len(pivots) < 4:
            return False, 0.0
        p = pivots[-4:]
        # L0 H1 L2 H3  — flag pole then lower-high lower-low channel
        L0, H1, L2, H3 = p[0].price, p[1].price, p[2].price, p[3].price
        k0, k1, k2, k3 = p[0].kind, p[1].kind, p[2].kind, p[3].kind
        if not (k0=="low" and k1=="high" and k2=="low" and k3=="high"):
            return False, 0.0
        pole_size = (H1 - L0) / L0
        flag_down = H3 < H1 and L2 < H1   # consolidation drifting down
        flag_small = (H1 - L2) < (H1 - L0) * 0.5  # flag < 50% of pole
        c = self._conf(pole_size > 0.03, flag_down, flag_small, H3 > L2)
        return c >= 0.6, c

    def test_bear_flag(self, pivots) -> tuple:
        if len(pivots) < 4:
            return False, 0.0
        p = pivots[-4:]
        H0, L1, H2, L3 = p[0].price, p[1].price, p[2].price, p[3].price
        k0, k1, k2, k3 = p[0].kind, p[1].kind, p[2].kind, p[3].kind
        if not (k0=="high" and k1=="low" and k2=="high" and k3=="low"):
            return False, 0.0
        pole_size = (H0 - L1) / H0
        flag_up = L3 > L1 and H2 > L1
        flag_small = (H2 - L1) < (H0 - L1) * 0.5
        c = self._conf(pole_size > 0.03, flag_up, flag_small, L3 < H2)
        return c >= 0.6, c

    def test_bull_pennant(self, pivots) -> tuple:
        # Like bull flag but consolidation is a symmetrical triangle
        if len(pivots) < 5:
            return False, 0.0
        p = pivots[-5:]
        L0, H1, L2, H3, L4 = [x.price for x in p]
        kinds = [x.kind for x in p]
        if kinds != ["low","high","low","high","low"]:
            return False, 0.0
        pole = (H1 - L0) / L0
        conv = H3 < H1 and L4 > L2   # converging highs/lows
        c = self._conf(pole > 0.03, conv, H3 > L4, H1 > H3)
        return c >= 0.6, c

    def test_bear_pennant(self, pivots) -> tuple:
        if len(pivots) < 5:
            return False, 0.0
        p = pivots[-5:]
        H0, L1, H2, L3, H4 = [x.price for x in p]
        kinds = [x.kind for x in p]
        if kinds != ["high","low","high","low","high"]:
            return False, 0.0
        pole = (H0 - L1) / H0
        conv = H4 < H2 and L3 > L1
        c = self._conf(pole > 0.03, conv, L3 < H4, L1 < L3)
        return c >= 0.6, c

    def test_ascending_triangle(self, pivots) -> tuple:
        # Flat highs, rising lows
        if len(pivots) < 4:
            return False, 0.0
        highs = [p.price for p in pivots if p.kind=="high"][-2:]
        lows  = [p.price for p in pivots if p.kind=="low"][-2:]
        if len(highs) < 2 or len(lows) < 2:
            return False, 0.0
        flat_highs = self._eq(highs[0], highs[1])
        rising_lows = lows[1] > lows[0]
        c = self._conf(flat_highs, rising_lows, highs[-1] > lows[-1])
        return c >= 0.6, c

    def test_descending_triangle(self, pivots) -> tuple:
        if len(pivots) < 4:
            return False, 0.0
        highs = [p.price for p in pivots if p.kind=="high"][-2:]
        lows  = [p.price for p in pivots if p.kind=="low"][-2:]
        if len(highs) < 2 or len(lows) < 2:
            return False, 0.0
        flat_lows    = self._eq(lows[0], lows[1])
        falling_highs = highs[1] < highs[0]
        c = self._conf(flat_lows, falling_highs, highs[-1] > lows[-1])
        return c >= 0.6, c

    def test_symmetrical_triangle(self, pivots) -> tuple:
        if len(pivots) < 4:
            return False, 0.0
        highs = [p.price for p in pivots if p.kind=="high"][-2:]
        lows  = [p.price for p in pivots if p.kind=="low"][-2:]
        if len(highs) < 2 or len(lows) < 2:
            return False, 0.0
        conv = self._converging(highs[0], highs[1], lows[0], lows[1])
        c = self._conf(conv, not self._eq(highs[0],highs[1]), not self._eq(lows[0],lows[1]))
        return c >= 0.6, c

    def test_rising_wedge(self, pivots) -> tuple:
        # Both highs and lows rising but converging
        if len(pivots) < 4:
            return False, 0.0
        highs = [p.price for p in pivots if p.kind=="high"][-2:]
        lows  = [p.price for p in pivots if p.kind=="low"][-2:]
        if len(highs) < 2 or len(lows) < 2:
            return False, 0.0
        both_rising  = highs[1] > highs[0] and lows[1] > lows[0]
        converging   = (highs[1]-lows[1]) < (highs[0]-lows[0])
        c = self._conf(both_rising, converging)
        return c >= 0.6, c

    def test_falling_wedge(self, pivots) -> tuple:
        if len(pivots) < 4:
            return False, 0.0
        highs = [p.price for p in pivots if p.kind=="high"][-2:]
        lows  = [p.price for p in pivots if p.kind=="low"][-2:]
        if len(highs) < 2 or len(lows) < 2:
            return False, 0.0
        both_falling = highs[1] < highs[0] and lows[1] < lows[0]
        converging   = (highs[1]-lows[1]) < (highs[0]-lows[0])
        c = self._conf(both_falling, converging)
        return c >= 0.6, c

    def test_bull_channel(self, pivots) -> tuple:
        if len(pivots) < 4:
            return False, 0.0
        highs = [p.price for p in pivots if p.kind=="high"][-2:]
        lows  = [p.price for p in pivots if p.kind=="low"][-2:]
        if len(highs) < 2 or len(lows) < 2:
            return False, 0.0
        both_rising = highs[1] > highs[0] and lows[1] > lows[0]
        h_slope = self._slope(highs[0], highs[1], 1)
        l_slope = self._slope(lows[0],  lows[1],  1)
        parallel = self._parallel(h_slope, l_slope)
        c = self._conf(both_rising, parallel)
        return c >= 0.6, c

    def test_bear_channel(self, pivots) -> tuple:
        if len(pivots) < 4:
            return False, 0.0
        highs = [p.price for p in pivots if p.kind=="high"][-2:]
        lows  = [p.price for p in pivots if p.kind=="low"][-2:]
        if len(highs) < 2 or len(lows) < 2:
            return False, 0.0
        both_falling = highs[1] < highs[0] and lows[1] < lows[0]
        h_slope = self._slope(highs[0], highs[1], 1)
        l_slope = self._slope(lows[0],  lows[1],  1)
        parallel = self._parallel(h_slope, l_slope)
        c = self._conf(both_falling, parallel)
        return c >= 0.6, c

    def test_double_top(self, pivots) -> tuple:
        if len(pivots) < 3:
            return False, 0.0
        highs = [p for p in pivots if p.kind=="high"]
        lows  = [p for p in pivots if p.kind=="low"]
        if len(highs) < 2 or len(lows) < 1:
            return False, 0.0
        H1, H2 = highs[-2].price, highs[-1].price
        trough  = lows[-1].price
        eq_tops  = self._eq(H1, H2)
        below    = trough < H1 * (1 - self.tol)
        c = self._conf(eq_tops, below, H1 > trough, H2 > trough)
        return c >= 0.6, c

    def test_double_bottom(self, pivots) -> tuple:
        if len(pivots) < 3:
            return False, 0.0
        lows  = [p for p in pivots if p.kind=="low"]
        highs = [p for p in pivots if p.kind=="high"]
        if len(lows) < 2 or len(highs) < 1:
            return False, 0.0
        L1, L2 = lows[-2].price, lows[-1].price
        peak   = highs[-1].price
        eq_btm = self._eq(L1, L2)
        above  = peak > L1 * (1 + self.tol)
        c = self._conf(eq_btm, above, L1 < peak, L2 < peak)
        return c >= 0.6, c

    def test_head_and_shoulders(self, pivots) -> tuple:
        if len(pivots) < 5:
            return False, 0.0
        highs = [p for p in pivots if p.kind=="high"]
        lows  = [p for p in pivots if p.kind=="low"]
        if len(highs) < 3 or len(lows) < 2:
            return False, 0.0
        LS, H, RS = highs[-3].price, highs[-2].price, highs[-1].price
        NL1, NL2  = lows[-2].price,  lows[-1].price
        head_dominant = H > LS and H > RS
        shoulders_eq  = self._eq(LS, RS)
        neckline_flat = self._eq(NL1, NL2)
        c = self._conf(head_dominant, shoulders_eq, neckline_flat,
                       H > LS * 1.01, H > RS * 1.01)
        return c >= 0.6, c

    def test_inverse_hs(self, pivots) -> tuple:
        if len(pivots) < 5:
            return False, 0.0
        lows  = [p for p in pivots if p.kind=="low"]
        highs = [p for p in pivots if p.kind=="high"]
        if len(lows) < 3 or len(highs) < 2:
            return False, 0.0
        LS, H, RS = lows[-3].price, lows[-2].price, lows[-1].price
        NL1, NL2  = highs[-2].price, highs[-1].price
        head_lowest   = H < LS and H < RS
        shoulders_eq  = self._eq(LS, RS)
        neckline_flat = self._eq(NL1, NL2)
        c = self._conf(head_lowest, shoulders_eq, neckline_flat,
                       H < LS * 0.99, H < RS * 0.99)
        return c >= 0.6, c

    def test_triple_top(self, pivots) -> tuple:
        if len(pivots) < 5:
            return False, 0.0
        highs = [p for p in pivots if p.kind=="high"]
        lows  = [p for p in pivots if p.kind=="low"]
        if len(highs) < 3 or len(lows) < 2:
            return False, 0.0
        H1, H2, H3 = highs[-3].price, highs[-2].price, highs[-1].price
        all_eq = self._eq(H1, H2) and self._eq(H2, H3)
        below  = all(l.price < H1 * (1 - self.tol) for l in lows[-2:])
        c = self._conf(all_eq, below)
        return c >= 0.6, c

    def test_triple_bottom(self, pivots) -> tuple:
        if len(pivots) < 5:
            return False, 0.0
        lows  = [p for p in pivots if p.kind=="low"]
        highs = [p for p in pivots if p.kind=="high"]
        if len(lows) < 3 or len(highs) < 2:
            return False, 0.0
        L1, L2, L3 = lows[-3].price, lows[-2].price, lows[-1].price
        all_eq = self._eq(L1, L2) and self._eq(L2, L3)
        above  = all(h.price > L1 * (1 + self.tol) for h in highs[-2:])
        c = self._conf(all_eq, above)
        return c >= 0.6, c

    def test_broadening_top(self, pivots) -> tuple:
        if len(pivots) < 4:
            return False, 0.0
        highs = [p.price for p in pivots if p.kind=="high"][-2:]
        lows  = [p.price for p in pivots if p.kind=="low"][-2:]
        if len(highs) < 2 or len(lows) < 2:
            return False, 0.0
        div = self._diverging(highs[0], highs[1], lows[0], lows[1])
        # Context: price coming from a high area
        c = self._conf(div, highs[1] > lows[1])
        return c >= 0.6, c

    def test_broadening_bottom(self, pivots) -> tuple:
        if len(pivots) < 4:
            return False, 0.0
        highs = [p.price for p in pivots if p.kind=="high"][-2:]
        lows  = [p.price for p in pivots if p.kind=="low"][-2:]
        if len(highs) < 2 or len(lows) < 2:
            return False, 0.0
        div = self._diverging(highs[0], highs[1], lows[0], lows[1])
        c = self._conf(div, highs[1] > lows[1])
        return c >= 0.6, c

    def test_cup_and_handle(self, pivots) -> tuple:
        # Cup: left high → low → right high (roughly equal), then handle = small pullback
        if len(pivots) < 5:
            return False, 0.0
        highs = [p for p in pivots if p.kind=="high"]
        lows  = [p for p in pivots if p.kind=="low"]
        if len(highs) < 2 or len(lows) < 2:
            return False, 0.0
        cup_left  = highs[-2].price
        cup_right = highs[-1].price
        cup_low   = lows[-2].price
        handle_low = lows[-1].price
        rims_eq   = self._eq(cup_left, cup_right)
        deep_cup  = cup_low < cup_left * 0.92   # cup at least 8% deep
        handle_small = (cup_right - handle_low) < (cup_right - cup_low) * 0.5
        c = self._conf(rims_eq, deep_cup, handle_small,
                       handle_low > cup_low, cup_right > handle_low)
        return c >= 0.6, c

    # ---- Run all tests ----

    def run_all(self, pivots: list) -> PatternResult:
        """
        Run all 20 pattern tests.
        Returns the highest-confidence match, or a blank PatternResult.

        Test order matters for ties: high-conviction reversal patterns are
        checked first so they win when confidence is equal to a simpler
        continuation pattern (e.g. H&S vs Bear Pennant on the same pivots).
        """
        tests = [
            # --- High-conviction reversals first ---
            ("Head & Shoulders",     self.test_head_and_shoulders),
            ("Inverse H&S",          self.test_inverse_hs),
            ("Triple Top",           self.test_triple_top),
            ("Triple Bottom",        self.test_triple_bottom),
            ("Cup & Handle",         self.test_cup_and_handle),
            ("Double Top",           self.test_double_top),
            ("Double Bottom",        self.test_double_bottom),
            # --- Broadening (reversal) ---
            ("Broadening Top",       self.test_broadening_top),
            ("Broadening Bottom",    self.test_broadening_bottom),
            # --- Continuation patterns ---
            ("Bull Flag",            self.test_bull_flag),
            ("Bear Flag",            self.test_bear_flag),
            ("Bull Pennant",         self.test_bull_pennant),
            ("Bear Pennant",         self.test_bear_pennant),
            ("Ascending Triangle",   self.test_ascending_triangle),
            ("Descending Triangle",  self.test_descending_triangle),
            ("Symmetrical Triangle", self.test_symmetrical_triangle),
            ("Rising Wedge",         self.test_rising_wedge),
            ("Falling Wedge",        self.test_falling_wedge),
            ("Bull Channel",         self.test_bull_channel),
            ("Bear Channel",         self.test_bear_channel),
        ]

        best_name = None
        best_conf = 0.0

        for name, fn in tests:
            try:
                matched, conf = fn(pivots)
                if matched and conf > best_conf:
                    best_conf = conf
                    best_name = name
            except Exception as e:
                logger.debug(f"Pattern test {name} error: {e}")

        if best_name is None:
            return PatternResult(pattern_found=False)

        raw_dir = PATTERN_DIRECTIONS.get(best_name, "neutral")
        # Normalize raw direction to simple direction for display
        simple_dir = raw_dir.replace("_strong", "")

        return PatternResult(
            name          = best_name,
            direction     = simple_dir,
            confidence    = round(best_conf, 3),
            pivots        = pivots,
            pattern_found = True,
            raw_direction = raw_dir,
        )


# ---------------------------------------------------------------------------
# Public API: PatternEngine
# ---------------------------------------------------------------------------

class PatternEngine:
    """
    Main entry point for PMO Bot.

    engine = PatternEngine()
    result = engine.detect(bars, trade_direction="long")
    print(result)                        # Bull Flag (bullish, conf=0.78, mod=+6)
    print(result.score_modifier)         # +6
    print(result.get_journal_dict())     # dict for CSV logging
    """

    def __init__(self,
                 zigzag_depth: int = ZIGZAG_DEPTH,
                 zigzag_deviation: float = ZIGZAG_DEVIATION,
                 tolerance: float = TOLERANCE):
        self._zz = ZigZag(depth=zigzag_depth, deviation=zigzag_deviation)
        self._matcher = PatternMatcher(tolerance=tolerance)

    def detect(self, bars: list, trade_direction: str = "long") -> PatternResult:
        """
        bars: list of dicts, each with keys:
              'open', 'high', 'low', 'close', 'volume', 'datetime'
              Ordered oldest → newest, minimum ~40 bars recommended.

        trade_direction: 'long' or 'short' — used for score modifier calculation.

        Returns: PatternResult
        """
        if len(bars) < 20:
            logger.debug("PatternEngine: too few bars (%d), skipping", len(bars))
            return PatternResult(pattern_found=False)

        # Step 1: compute zigzag pivots
        pivots = self._zz.compute(bars)
        if len(pivots) < 3:
            logger.debug("PatternEngine: too few pivots (%d), no pattern", len(pivots))
            return PatternResult(pattern_found=False)

        # Step 2: match patterns
        result = self._matcher.run_all(pivots)

        # Step 3: compute score modifier
        if result.pattern_found:
            td = trade_direction.lower().strip()
            raw_dir = result.raw_direction or result.direction or "neutral"
            modifier_key = (raw_dir, td)
            result.score_modifier = SCORE_MODIFIERS.get(modifier_key, 0)
            logger.info(
                "PatternEngine: %s | direction=%s | conf=%.2f | trade=%s | mod=%+d",
                result.name, result.direction, result.confidence,
                trade_direction, result.score_modifier
            )

        return result

    def get_score_modifier(self, bars: list, trade_direction: str = "long") -> int:
        """
        Convenience method — returns just the integer score modifier.
        Returns 0 if no pattern detected.
        """
        return self.detect(bars, trade_direction).score_modifier


# ---------------------------------------------------------------------------
# Integration helpers for pmo_bot.py
# ---------------------------------------------------------------------------

def apply_pattern_to_score(base_score: float,
                            bars: list,
                            trade_direction: str = "long",
                            engine: Optional[PatternEngine] = None) -> tuple:
    """
    Drop-in helper to apply pattern modifier to an existing PMO score.

    Returns: (adjusted_score, pattern_result)

    Example in pmo_bot.py:
        adjusted_score, pattern = apply_pattern_to_score(
            pmo_score, intraday_bars, "long"
        )
        # Log pattern.get_journal_dict() to trade journal
    """
    if engine is None:
        engine = PatternEngine()
    result = engine.detect(bars, trade_direction)
    adjusted = base_score + result.score_modifier
    return adjusted, result


# ---------------------------------------------------------------------------
# Standalone test / smoke check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random
    import datetime

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("PMO Pattern Engine — smoke test\n")

    def make_bars(n=80, seed=42):
        random.seed(seed)
        bars = []
        price = 100.0
        t = datetime.datetime(2026, 1, 2, 9, 30)
        for i in range(n):
            chg = random.gauss(0, 0.5)
            o = price
            c = price + chg
            h = max(o, c) + random.uniform(0, 0.3)
            l = min(o, c) - random.uniform(0, 0.3)
            bars.append({
                "open": round(o, 2), "high": round(h, 2),
                "low":  round(l, 2), "close": round(c, 2),
                "volume": random.randint(10000, 100000),
                "datetime": t,
            })
            price = c
            t += datetime.timedelta(minutes=5)
        return bars

    engine = PatternEngine()
    bars = make_bars(80)

    for direction in ["long", "short"]:
        result = engine.detect(bars, direction)
        print(f"Trade direction: {direction}")
        print(f"  Result     : {result}")
        print(f"  Journal    : {result.get_journal_dict()}")
        print()

    # Test apply_pattern_to_score helper
    adj, pat = apply_pattern_to_score(75.0, bars, "long")
    print(f"Score adjustment: 75.0 → {adj} ({pat})")
    print("\nSmoke test complete.")