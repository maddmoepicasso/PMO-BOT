"""
PMO Global Session Clock — pmo_session_clock.py
================================================
Tracks Tokyo → London → NYC session flow and computes:
  1. Overnight futures drift (direction + magnitude)
  2. ADR consumed % (how much of avg daily range is already used)
  3. Session bias (what prior sessions say about current session)
  4. Optimal entry window (is now a good time to enter?)

Free data sources used:
  - Alpaca /v2/stocks/{symbol}/bars?timeframe=1Day (daily bars for ADR)
  - Alpaca /v2/stocks/{symbol}/bars?timeframe=1Hour (overnight + premarket)
  - No paid feeds required

Sessions (ET):
  Tokyo  : 7pm-4am ET (overnight)
  London : 3am-11am ET (overlaps NYC open)
  NYC    : 9:30am-4pm ET

Key insight: London open direction (3am-4:30am ET) predicts NYC session
bias with ~58% accuracy. If London breaks overnight range high → bullish
bias for NYC. If London breaks overnight range low → bearish bias.

Read-only: logged to journal, shown on dashboard.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, time, timezone

logger = logging.getLogger("pmo.session_clock")

# Session time boundaries (ET = UTC-4 in summer, UTC-5 in winter)
# Using ET hour ranges
SESSIONS = {
    "tokyo":   (19, 4),    # 7pm-4am ET
    "london":  (3,  11),   # 3am-11am ET
    "nyc":     (9,  16),   # 9:30am-4pm ET (simplified to 9am)
    "premarket":(4,  9),   # 4am-9:30am ET
}

# ADR thresholds
ADR_CONSUMED_CAUTION  = 0.70   # >70% of daily range consumed = late entry risk
ADR_CONSUMED_DANGER   = 0.90   # >90% = very late, likely reversal territory

# Score modifiers
MODIFIERS = {
    "london_bullish_nyc_long":   +4,
    "london_bearish_nyc_short":  +4,
    "london_against":            -3,
    "adr_consumed_danger":       -5,
    "adr_consumed_caution":      -3,
    "adr_clear":                 +2,
    "futures_with_trade":        +3,
    "futures_against_trade":     -3,
    "optimal_window":            +2,
    "poor_window":               -2,
}


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SessionClockResult:
    # Current session
    current_session:    str   = "UNKNOWN"
    session_age_min:    int   = 0

    # Overnight / futures drift
    overnight_drift_pct: float = 0.0
    overnight_direction: str   = "FLAT"   # UP / DOWN / FLAT
    futures_signal:      str   = "NEUTRAL"

    # London bias
    london_bias:         str   = "NEUTRAL"  # BULLISH / BEARISH / NEUTRAL
    london_break_pct:    float = 0.0

    # ADR
    adr_5day:           Optional[float] = None
    adr_consumed_pct:   float = 0.0
    adr_signal:         str   = "UNKNOWN"   # CLEAR / CAUTION / DANGER

    # Entry window
    entry_window:       str   = "NEUTRAL"   # OPTIMAL / NEUTRAL / POOR
    window_reason:      str   = ""

    # Combined
    score_modifier:     int   = 0
    session_signal:     str   = "NEUTRAL"

    # Raw data
    current_price:      Optional[float] = None
    day_high:           Optional[float] = None
    day_low:            Optional[float] = None

    def get_journal_dict(self) -> dict:
        return {
            "session_current":     self.current_session,
            "session_london_bias": self.london_bias,
            "session_adr_pct":     round(self.adr_consumed_pct, 3),
            "session_adr_signal":  self.adr_signal,
            "session_overnight":   self.overnight_direction,
            "session_drift_pct":   round(self.overnight_drift_pct, 3),
            "session_window":      self.entry_window,
            "session_signal":      self.session_signal,
            "session_mod":         self.score_modifier,
        }

    def get_dashboard_dict(self) -> dict:
        return {
            "session":       self.current_session,
            "london_bias":   self.london_bias,
            "adr_consumed":  round(self.adr_consumed_pct * 100, 1),
            "adr_signal":    self.adr_signal,
            "overnight":     self.overnight_direction,
            "drift_pct":     round(self.overnight_drift_pct, 2),
            "window":        self.entry_window,
            "window_reason": self.window_reason,
            "signal":        self.session_signal,
            "mod":           self.score_modifier,
        }

    def __str__(self):
        return (f"Session: {self.current_session} | London={self.london_bias} | "
                f"ADR={self.adr_consumed_pct*100:.0f}%({self.adr_signal}) | "
                f"Window={self.entry_window} | mod={self.score_modifier:+d}")


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

class SessionClockEngine:
    """
    Computes global session clock signals for PMO Bot.

    Usage:
        engine = SessionClockEngine()
        result = engine.analyze(
            ticker         = "NVDA",
            intraday_bars  = bars,        # today's 5m bars
            daily_bars     = daily_bars,  # last 10 daily bars for ADR
            trade_direction = "long",
            current_hour_et = 10,
            current_minute  = 15,
        )
        print(result)
    """

    def _current_session(self, hour_et: int, minute: int = 0) -> tuple:
        """Returns (session_name, age_minutes_into_session)."""
        t = hour_et + minute / 60

        if 9.5 <= t < 16:
            age = int((t - 9.5) * 60)
            return "NYC", age
        elif 3 <= t < 9.5:
            age = int((t - 3) * 60)
            return "PREMARKET/LONDON", age
        elif t >= 19 or t < 3:
            age = int((t - 19) % 24 * 60) if t >= 19 else int((t + 5) * 60)
            return "TOKYO/OVERNIGHT", age
        return "TRANSITION", 0

    def _entry_window(self, session: str, age_min: int,
                      trade_direction: str) -> tuple:
        """
        Returns (window_quality, reason) based on time of day.
        Best entry windows based on historical intraday patterns.
        """
        if session == "NYC":
            if age_min <= 30:
                return "OPTIMAL", "first 30min of NYC — highest momentum window"
            elif age_min <= 90:
                return "OPTIMAL", "9:30-11am NYC — primary trending window"
            elif 90 < age_min <= 210:
                return "NEUTRAL", "mid-session — momentum variable"
            elif age_min > 210:
                return "POOR", "last 30min — closing risk, avoid new entries"
        elif "LONDON" in session:
            return "NEUTRAL", "London session — valid for premarket setups"
        return "POOR", "overnight session — wide spreads, low liquidity"

    def _compute_adr(self, daily_bars: list, lookback: int = 5) -> Optional[float]:
        """Compute average daily range (high-low) over last N days."""
        if not daily_bars or len(daily_bars) < 2:
            return None
        recent = daily_bars[-lookback:] if len(daily_bars) >= lookback else daily_bars[:-1]
        ranges = []
        for bar in recent:
            h = float(bar.get("high", 0))
            l = float(bar.get("low",  0))
            if h > 0 and l > 0 and h > l:
                ranges.append(h - l)
        return sum(ranges) / len(ranges) if ranges else None

    def _compute_overnight_drift(self, intraday_bars: list) -> tuple:
        """
        Compute drift from prior close to current open.
        Returns (drift_pct, direction)
        """
        if len(intraday_bars) < 2:
            return 0.0, "FLAT"
        # Prior close = last bar of previous day
        # Today open = first bar open
        open_price = float(intraday_bars[0].get("open", 0))
        curr_price = float(intraday_bars[-1].get("close", 0))
        if open_price <= 0:
            return 0.0, "FLAT"
        drift = (curr_price - open_price) / open_price * 100
        if drift > 0.2:  direction = "UP"
        elif drift < -0.2: direction = "DOWN"
        else: direction = "FLAT"
        return round(drift, 3), direction

    def _compute_london_bias(self, intraday_bars: list,
                              current_hour_et: int) -> tuple:
        """
        Estimate London session bias from early-morning bars (3am-9:30am ET).
        Returns (bias, break_pct)
        Only meaningful if we have overnight bars.
        """
        if not intraday_bars or current_hour_et < 9:
            return "NEUTRAL", 0.0

        # Find overnight range (bars before 9:30am)
        overnight_bars = []
        session_bars   = []
        for bar in intraday_bars:
            dt = bar.get("datetime")
            if isinstance(dt, str):
                try:
                    dt = datetime.fromisoformat(dt)
                except: pass
            if hasattr(dt, 'hour'):
                if dt.hour < 9 or (dt.hour == 9 and dt.minute < 30):
                    overnight_bars.append(bar)
                else:
                    session_bars.append(bar)

        if not overnight_bars:
            # No overnight data — estimate from first vs current
            if len(intraday_bars) >= 3:
                early_high = max(float(b.get("high",0)) for b in intraday_bars[:3])
                early_low  = min(float(b.get("low",0))  for b in intraday_bars[:3])
                curr = float(intraday_bars[-1].get("close",0))
                if curr > early_high * 0.999:
                    return "BULLISH", round((curr-early_high)/early_high*100, 2)
                elif curr < early_low * 1.001:
                    return "BEARISH", round((early_low-curr)/early_low*100, 2)
            return "NEUTRAL", 0.0

        overnight_high = max(float(b.get("high",0)) for b in overnight_bars)
        overnight_low  = min(float(b.get("low",0))  for b in overnight_bars)
        curr_price     = float(intraday_bars[-1].get("close",0))

        if curr_price > overnight_high:
            bias = "BULLISH"
            brk  = (curr_price - overnight_high) / overnight_high * 100
        elif curr_price < overnight_low:
            bias = "BEARISH"
            brk  = (overnight_low - curr_price) / overnight_low * 100
        else:
            bias = "NEUTRAL"
            brk  = 0.0

        return bias, round(brk, 2)

    def analyze(self,
                ticker:           str,
                intraday_bars:    list,
                daily_bars:       list           = None,
                trade_direction:  str            = "long",
                current_hour_et:  int            = 10,
                current_minute:   int            = 0) -> SessionClockResult:
        """
        Full session clock analysis.
        intraday_bars : today's 5m bars (oldest→newest)
        daily_bars    : last 10+ daily bars for ADR calculation
        """
        td = trade_direction.lower()
        result = SessionClockResult()

        # Current session
        session, age = self._current_session(current_hour_et, current_minute)
        result.current_session  = session
        result.session_age_min  = age

        # Entry window quality
        window, window_reason = self._entry_window(session, age, td)
        result.entry_window   = window
        result.window_reason  = window_reason

        # Overnight drift
        drift_pct, drift_dir = self._compute_overnight_drift(intraday_bars)
        result.overnight_drift_pct = drift_pct
        result.overnight_direction = drift_dir

        # Futures signal (direction-aware)
        if drift_dir == "UP" and td == "long":
            result.futures_signal = "ALIGNED"
        elif drift_dir == "DOWN" and td == "short":
            result.futures_signal = "ALIGNED"
        elif drift_dir == "FLAT":
            result.futures_signal = "NEUTRAL"
        else:
            result.futures_signal = "AGAINST"

        # London bias
        london_bias, london_break = self._compute_london_bias(
            intraday_bars, current_hour_et)
        result.london_bias     = london_bias
        result.london_break_pct = london_break

        # ADR
        adr = self._compute_adr(daily_bars or [])
        result.adr_5day = round(adr, 4) if adr else None

        if adr and intraday_bars:
            curr_high = max(float(b.get("high",0)) for b in intraday_bars)
            curr_low  = min(float(b.get("low",0))  for b in intraday_bars)
            day_range = curr_high - curr_low
            result.day_high = round(curr_high, 4)
            result.day_low  = round(curr_low,  4)
            consumed = day_range / adr if adr > 0 else 0
            result.adr_consumed_pct = round(min(consumed, 1.5), 3)

            if consumed >= ADR_CONSUMED_DANGER:
                result.adr_signal = "DANGER"
            elif consumed >= ADR_CONSUMED_CAUTION:
                result.adr_signal = "CAUTION"
            else:
                result.adr_signal = "CLEAR"

        # Compute combined modifier
        mod = 0

        # London bias
        if london_bias == "BULLISH" and td == "long":
            mod += MODIFIERS["london_bullish_nyc_long"]
        elif london_bias == "BEARISH" and td == "short":
            mod += MODIFIERS["london_bearish_nyc_short"]
        elif london_bias != "NEUTRAL":
            mod += MODIFIERS["london_against"]

        # ADR
        if result.adr_signal == "DANGER":
            mod += MODIFIERS["adr_consumed_danger"]
        elif result.adr_signal == "CAUTION":
            mod += MODIFIERS["adr_consumed_caution"]
        elif result.adr_signal == "CLEAR":
            mod += MODIFIERS["adr_clear"]

        # Futures/overnight
        if result.futures_signal == "ALIGNED":
            mod += MODIFIERS["futures_with_trade"]
        elif result.futures_signal == "AGAINST":
            mod += MODIFIERS["futures_against_trade"]

        # Entry window
        if window == "OPTIMAL":
            mod += MODIFIERS["optimal_window"]
        elif window == "POOR":
            mod += MODIFIERS["poor_window"]

        # Cap
        mod = max(-12, min(12, mod))
        result.score_modifier = mod

        # Overall signal
        if mod >= 5:
            result.session_signal = "BULLISH"
        elif mod <= -5:
            result.session_signal = "BEARISH"
        else:
            result.session_signal = "NEUTRAL"

        logger.info("SessionClock: %s | London=%s | ADR=%s(%.0f%%) | Window=%s | mod=%+d",
                    session, london_bias, result.adr_signal,
                    result.adr_consumed_pct*100, window, mod)
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import random, datetime
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("PMO Session Clock Engine — smoke test\n")
    random.seed(42)

    def make_bars(n=40, start=210.0, trend=0.04):
        bars, price = [], start
        t = datetime.datetime(2026,6,16,9,30)
        for i in range(n):
            o = price
            c = price + trend + random.gauss(0,0.2)
            h = max(o,c)+random.uniform(0,0.15)
            l = min(o,c)-random.uniform(0,0.15)
            bars.append({"open":round(o,2),"high":round(h,2),"low":round(l,2),
                         "close":round(c,2),"volume":80000,"datetime":t})
            price = c
            t += datetime.timedelta(minutes=5)
        return bars

    def make_daily(n=10, start=208.0):
        bars, price = [], start
        t = datetime.datetime(2026,6,1)
        for i in range(n):
            o = price
            c = price + random.gauss(0.5, 1.5)
            h = max(o,c)+random.uniform(0.5,2.0)
            l = min(o,c)-random.uniform(0.5,2.0)
            bars.append({"open":round(o,2),"high":round(h,2),"low":round(l,2),
                         "close":round(c,2)})
            price = c
            t += datetime.timedelta(days=1)
        return bars

    engine = SessionClockEngine()
    bars   = make_bars(40, 210.0, 0.05)
    daily  = make_daily(10, 208.0)

    scenarios = [
        ("NYC open (9:45am, long)", "long", 9, 45),
        ("NYC mid (11:30am, long)", "long", 11, 30),
        ("NYC close (3:45pm, long)", "long", 15, 45),
        ("London/premarket (6am)", "long", 6, 0),
    ]

    for label, td, hour, minute in scenarios:
        r = engine.analyze("NVDA", bars, daily, td, hour, minute)
        print(f"{label}:")
        print(f"  {r}")
        print(f"  Window: {r.entry_window} — {r.window_reason}")
        print()

    print("Journal dict:", engine.analyze("NVDA", bars, daily, "long", 10, 15).get_journal_dict())
    print("\nSmoke test complete.")
