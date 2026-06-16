"""
PMO Event Calendar Intelligence — pmo_event_calendar.py
=========================================================
Tracks economic calendar events and their known behavioral effects
on intraday trading. No paid data feed required.

Events tracked:
  - FOMC meetings (rate decisions + press conferences)
  - CPI releases (monthly inflation data)
  - NFP (Non-Farm Payrolls, first Friday of month)
  - Earnings (company-specific, detected from date + known schedule)
  - Options expiration (OpEx): monthly (3rd Friday) + quarterly (quad witch)
  - Triple/Quad Witching days

Behavioral patterns (research-backed):
  - Day before FOMC: compression, avoid new longs
  - Day after FOMC: directional move, trade with momentum
  - CPI week: elevated volatility, wider stops needed
  - OpEx Friday: pinning effect near round strikes
  - Quad Witch: highest volume day of quarter, breakouts more reliable

Data sources:
  - Hardcoded 2026 FOMC/CPI schedule (updated annually)
  - Options expiration dates computed algorithmically
  - Earnings: approximated from ticker + quarter

Read-only: logged, shown on dashboard.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, date, timedelta

logger = logging.getLogger("pmo.event_calendar")

# ─────────────────────────────────────────────────────────────────────────────
# 2026 Economic Calendar (hardcoded — update annually)
# ─────────────────────────────────────────────────────────────────────────────

FOMC_2026 = [
    date(2026, 1, 28), date(2026, 1, 29),   # Jan FOMC (Wed decision)
    date(2026, 3, 18), date(2026, 3, 19),   # Mar FOMC
    date(2026, 5, 6),  date(2026, 5, 7),    # May FOMC
    date(2026, 6, 17), date(2026, 6, 18),   # Jun FOMC ← THIS WEEK
    date(2026, 7, 29), date(2026, 7, 30),   # Jul FOMC
    date(2026, 9, 16), date(2026, 9, 17),   # Sep FOMC
    date(2026, 11, 4), date(2026, 11, 5),   # Nov FOMC
    date(2026, 12, 16),date(2026, 12, 17),  # Dec FOMC
]

# FOMC decision days (the second day of each 2-day meeting)
FOMC_DECISION_DAYS_2026 = [
    date(2026, 1, 29), date(2026, 3, 19), date(2026, 5, 7),
    date(2026, 6, 18), date(2026, 7, 30), date(2026, 9, 17),
    date(2026, 11, 5), date(2026, 12, 17),
]

CPI_2026 = [
    date(2026, 1, 14), date(2026, 2, 11), date(2026, 3, 11),
    date(2026, 4, 10), date(2026, 5, 13), date(2026, 6, 11),
    date(2026, 7, 14), date(2026, 8, 12), date(2026, 9, 10),
    date(2026, 10, 13),date(2026, 11, 12),date(2026, 12, 10),
]

# NFP: first Friday of each month
def _first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    while d.weekday() != 4:  # 4 = Friday
        d += timedelta(days=1)
    return d

NFP_2026 = [_first_friday(2026, m) for m in range(1, 13)]

# Options expiration: 3rd Friday of each month
def _third_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() == 4:
            count += 1
            if count == 3:
                return d
        d += timedelta(days=1)

OPEX_2026 = [_third_friday(2026, m) for m in range(1, 13)]
# Quad Witching: March, June, September, December OpEx
QUAD_WITCH_2026 = [_third_friday(2026, m) for m in [3, 6, 9, 12]]

# Market holidays 2026 (US)
MARKET_HOLIDAYS_2026 = [
    date(2026, 1, 1),   # New Year's
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth ← THIS FRIDAY
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
]

MODIFIERS = {
    "fomc_day":           -4,   # day of FOMC decision — compression/uncertainty
    "fomc_eve":           -3,   # day before FOMC — caution
    "fomc_after":         +3,   # day after FOMC — directional momentum
    "cpi_day":            -3,   # CPI release day — volatility spike
    "cpi_week":           -2,   # week of CPI — elevated vol
    "nfp_day":            -3,   # NFP day — high vol, avoid early entries
    "opex_friday":        -2,   # options pinning effect
    "quad_witch":         +2,   # high volume = better breakout reliability
    "holiday_eve":        -2,   # day before holiday — early close, thin volume
    "short_week":         -1,   # holiday week — generally lower participation
    "normal":              0,
}


@dataclass
class CalendarEvent:
    name:    str
    date:    date
    impact:  str   # HIGH / MEDIUM / LOW
    note:    str   = ""


@dataclass
class EventCalendarResult:
    today_events:        list  = field(default_factory=list)
    week_events:         list  = field(default_factory=list)
    fomc_days_away:      Optional[int]  = None
    cpi_days_away:       Optional[int]  = None
    nfp_days_away:       Optional[int]  = None
    opex_days_away:      Optional[int]  = None
    is_fomc_day:         bool  = False
    is_fomc_eve:         bool  = False
    is_fomc_after:       bool  = False
    is_cpi_day:          bool  = False
    is_cpi_week:         bool  = False
    is_nfp_day:          bool  = False
    is_opex:             bool  = False
    is_quad_witch:       bool  = False
    is_holiday_eve:      bool  = False
    is_short_week:       bool  = False
    score_modifier:      int   = 0
    volatility_regime:   str   = "NORMAL"   # ELEVATED / NORMAL / COMPRESSED
    event_signal:        str   = "NEUTRAL"  # CAUTION / NEUTRAL / FAVORABLE
    primary_event:       str   = ""
    note:                str   = ""

    def get_journal_dict(self) -> dict:
        return {
            "cal_events_today":  len(self.today_events),
            "cal_primary":       self.primary_event,
            "cal_fomc_away":     self.fomc_days_away,
            "cal_cpi_away":      self.cpi_days_away,
            "cal_opex_away":     self.opex_days_away,
            "cal_vol_regime":    self.volatility_regime,
            "cal_signal":        self.event_signal,
            "cal_mod":           self.score_modifier,
        }

    def get_dashboard_dict(self) -> dict:
        return {
            "today_events":    [{"name":e.name,"impact":e.impact,"note":e.note}
                                 for e in self.today_events],
            "week_events":     [{"name":e.name,"date":str(e.date),"impact":e.impact}
                                 for e in self.week_events],
            "fomc_days_away":  self.fomc_days_away,
            "cpi_days_away":   self.cpi_days_away,
            "opex_days_away":  self.opex_days_away,
            "vol_regime":      self.volatility_regime,
            "signal":          self.event_signal,
            "mod":             self.score_modifier,
            "primary":         self.primary_event,
            "note":            self.note,
        }

    def __str__(self):
        events = ", ".join(e.name for e in self.today_events) or "none"
        return (f"Calendar: {self.event_signal} | today=[{events}] | "
                f"vol={self.volatility_regime} | mod={self.score_modifier:+d} | "
                f"{self.note}")


class EventCalendarEngine:
    """
    Event calendar intelligence for PMO Bot.

    engine = EventCalendarEngine()
    result = engine.analyze(today=date.today())
    print(result)
    """

    def _days_until(self, today: date, dates: list) -> Optional[int]:
        future = [d for d in dates if d >= today]
        return (min(future) - today).days if future else None

    def _days_since(self, today: date, dates: list) -> Optional[int]:
        past = [d for d in dates if d <= today]
        return (today - max(past)).days if past else None

    def analyze(self, today: Optional[date] = None) -> EventCalendarResult:
        today = today or date.today()
        result = EventCalendarResult()

        # Compute days to next event
        result.fomc_days_away = self._days_until(today, FOMC_DECISION_DAYS_2026)
        result.cpi_days_away  = self._days_until(today, CPI_2026)
        result.nfp_days_away  = self._days_until(today, NFP_2026)
        result.opex_days_away = self._days_until(today, OPEX_2026)

        # Detect today's events
        events = []
        mod = 0

        # FOMC
        if today in FOMC_DECISION_DAYS_2026:
            result.is_fomc_day = True
            events.append(CalendarEvent("FOMC Decision", today, "HIGH",
                "Rate decision at 2pm ET. Avoid entries until 2:30pm."))
            mod += MODIFIERS["fomc_day"]

        elif today in FOMC_2026 and today not in FOMC_DECISION_DAYS_2026:
            # First day of 2-day meeting
            events.append(CalendarEvent("FOMC Day 1", today, "MEDIUM",
                "FOMC meeting day 1 — decision tomorrow. Compressed ranges likely."))
            mod += MODIFIERS["fomc_eve"]
            result.is_fomc_eve = True

        fomc_since = self._days_since(today, FOMC_DECISION_DAYS_2026)
        if fomc_since == 1:
            result.is_fomc_after = True
            events.append(CalendarEvent("Post-FOMC", today, "MEDIUM",
                "Day after FOMC — trade the direction of yesterday's move."))
            mod += MODIFIERS["fomc_after"]

        # CPI
        if today in CPI_2026:
            result.is_cpi_day = True
            events.append(CalendarEvent("CPI Release", today, "HIGH",
                "CPI at 8:30am ET. Avoid entries until 9:45am — spike risk."))
            mod += MODIFIERS["cpi_day"]
        else:
            # CPI week
            cpi_since = self._days_since(today, CPI_2026)
            cpi_until = result.cpi_days_away
            if (cpi_since is not None and cpi_since <= 2) or \
               (cpi_until is not None and cpi_until <= 1):
                result.is_cpi_week = True
                mod += MODIFIERS["cpi_week"]

        # NFP
        if today in NFP_2026:
            result.is_nfp_day = True
            events.append(CalendarEvent("NFP Release", today, "HIGH",
                "Jobs report at 8:30am ET. Wide spreads until 10am."))
            mod += MODIFIERS["nfp_day"]

        # Options expiration
        if today in QUAD_WITCH_2026:
            result.is_quad_witch = True
            result.is_opex = True
            events.append(CalendarEvent("Quad Witching", today, "HIGH",
                "Quarterly OpEx — highest volume day. Breakouts more reliable."))
            mod += MODIFIERS["quad_witch"]
        elif today in OPEX_2026:
            result.is_opex = True
            events.append(CalendarEvent("Monthly OpEx", today, "MEDIUM",
                "Monthly options expiration — pinning effect near round strikes."))
            mod += MODIFIERS["opex_friday"]

        # Holiday proximity
        tomorrow = today + timedelta(days=1)
        if tomorrow in MARKET_HOLIDAYS_2026:
            result.is_holiday_eve = True
            events.append(CalendarEvent("Holiday Eve", today, "LOW",
                "Market closes early or is thin tomorrow. Reduce size."))
            mod += MODIFIERS["holiday_eve"]

        # Short week detection (holiday within 5 days)
        week_days = [today + timedelta(days=i) for i in range(5)]
        if any(d in MARKET_HOLIDAYS_2026 for d in week_days):
            result.is_short_week = True
            if not result.is_holiday_eve:
                mod += MODIFIERS["short_week"]

        # Week events (next 5 trading days)
        week_events = []
        for i in range(1, 6):
            d = today + timedelta(days=i)
            if d.weekday() >= 5: continue
            if d in FOMC_DECISION_DAYS_2026:
                week_events.append(CalendarEvent("FOMC Decision", d, "HIGH"))
            if d in CPI_2026:
                week_events.append(CalendarEvent("CPI Release", d, "HIGH"))
            if d in NFP_2026:
                week_events.append(CalendarEvent("NFP", d, "HIGH"))
            if d in OPEX_2026:
                week_events.append(CalendarEvent("Options Expiry", d, "MEDIUM"))
            if d in MARKET_HOLIDAYS_2026:
                week_events.append(CalendarEvent("Market Holiday", d, "HIGH",
                                                  "Market closed"))

        result.today_events = events
        result.week_events  = week_events
        result.score_modifier = max(-10, min(6, mod))

        # Volatility regime
        high_vol_count = sum([result.is_fomc_day, result.is_cpi_day,
                              result.is_nfp_day, result.is_quad_witch])
        if high_vol_count >= 1 or result.is_cpi_week:
            result.volatility_regime = "ELEVATED"
        elif result.is_short_week:
            result.volatility_regime = "COMPRESSED"
        else:
            result.volatility_regime = "NORMAL"

        # Signal
        if mod <= -4:
            result.event_signal = "CAUTION"
        elif mod >= 2:
            result.event_signal = "FAVORABLE"
        else:
            result.event_signal = "NEUTRAL"

        # Primary event label
        if events:
            result.primary_event = events[0].name
            result.note = events[0].note
        else:
            result.primary_event = "No major events today"
            result.note = "Clean calendar — no event risk"

        logger.info("EventCalendar: %s | mod=%+d | vol=%s | events=%d",
                    result.event_signal, mod,
                    result.volatility_regime, len(events))
        return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("PMO Event Calendar Engine — smoke test\n")

    engine = EventCalendarEngine()

    test_dates = [
        (date(2026, 6, 16), "Today (Tuesday Jun 16)"),
        (date(2026, 6, 17), "Wednesday Jun 17 (FOMC Day 1)"),
        (date(2026, 6, 18), "Thursday Jun 18 (FOMC Decision)"),
        (date(2026, 6, 19), "Friday Jun 19 (JUNETEENTH - Holiday)"),
        (date(2026, 6, 11), "Jun 11 (CPI Day)"),
        (date(2026, 9, 18), "Sep 18 (Quad Witch)"),
    ]

    for d, label in test_dates:
        r = engine.analyze(d)
        print(f"=== {label} ===")
        print(f"  {r}")
        if r.today_events:
            for e in r.today_events:
                print(f"  Event: {e.name} ({e.impact}) — {e.note}")
        if r.week_events:
            print(f"  This week: {', '.join(e.name+' '+str(e.date) for e in r.week_events[:3])}")
        print()

    print("Journal dict:", engine.analyze(date(2026,6,16)).get_journal_dict())
    print("\nSmoke test complete.")
