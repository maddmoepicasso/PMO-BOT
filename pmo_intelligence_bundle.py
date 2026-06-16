"""
PMO Intelligence Bundle — pmo_intelligence_bundle.py
=====================================================
Runs all four advanced engines in one call:
  1. RegimeMemory    — historical PMO trade DNA
  2. SessionClock    — Tokyo/London/NYC session flow + ADR
  3. OrderFlow       — bid-ask pressure from bar data
  4. EventCalendar   — FOMC/CPI/NFP/OpEx awareness

Combined output:
  - Per-engine signals and modifiers
  - Combined modifier (capped at ±20)
  - Overall intelligence signal
  - Full journal dict (30 new columns)
  - Dashboard dict

Usage:
    from pmo_intelligence_bundle import IntelligenceBundle
    bundle = IntelligenceBundle()
    bundle.load_journal("pmo_bot_trade_journal.csv")

    result = bundle.analyze(
        ticker          = "NVDA",
        bars            = intraday_bars,
        daily_bars      = daily_bars,
        regime          = "MIXED",
        rvol            = 2.3,
        score           = 72.0,
        trade_direction = "long",
        today           = date.today(),
        current_hour_et = 10,
        current_minute  = 15,
    )
    print(result)
    print(result.get_journal_dict())

Read-only: PMO_INTELLIGENCE_READ_ONLY = True in pmo_settings.py
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import date, datetime

from pmo_regime_memory  import RegimeMemoryEngine,  RegimeMemoryResult
from pmo_session_clock  import SessionClockEngine,  SessionClockResult
from pmo_order_flow     import OrderFlowEngine,     OrderFlowResult
from pmo_event_calendar import EventCalendarEngine, EventCalendarResult

logger = logging.getLogger("pmo.intelligence_bundle")

COMBINED_CAP = 20   # max combined modifier across all 4 engines

INTELLIGENCE_SETTINGS = """
# ── Intelligence Bundle Settings (add to pmo_settings.py) ────────────────────
PMO_INTELLIGENCE_ENABLED       = True
PMO_INTELLIGENCE_READ_ONLY     = True    # True = log only, no score impact
PMO_REGMEM_ENABLED             = True    # Regime memory engine
PMO_SESSION_CLOCK_ENABLED      = True    # Global session clock
PMO_ORDER_FLOW_ENABLED         = True    # Order flow imbalance
PMO_EVENT_CALENDAR_ENABLED     = True    # Economic calendar
PMO_INTELLIGENCE_COMBINED_CAP  = 20      # Max combined modifier
# ─────────────────────────────────────────────────────────────────────────────
"""


@dataclass
class IntelligenceResult:
    regime_memory:  RegimeMemoryResult  = field(default_factory=RegimeMemoryResult)
    session_clock:  SessionClockResult  = field(default_factory=SessionClockResult)
    order_flow:     OrderFlowResult     = field(default_factory=OrderFlowResult)
    event_calendar: EventCalendarResult = field(default_factory=EventCalendarResult)

    combined_modifier: int  = 0
    intel_signal:      str  = "NEUTRAL"
    bull_count:        int  = 0
    bear_count:        int  = 0
    caution_flags:     list = field(default_factory=list)

    def get_journal_dict(self) -> dict:
        d = {}
        d.update(self.regime_memory.get_journal_dict())
        d.update(self.session_clock.get_journal_dict())
        d.update(self.order_flow.get_journal_dict())
        d.update(self.event_calendar.get_journal_dict())
        d["intel_combined_mod"] = self.combined_modifier
        d["intel_signal"]       = self.intel_signal
        d["intel_caution_flags"]= "; ".join(self.caution_flags) if self.caution_flags else ""
        return d

    def get_dashboard_dict(self) -> dict:
        return {
            "regime_memory":  self.regime_memory.get_dashboard_dict(),
            "session_clock":  self.session_clock.get_dashboard_dict(),
            "order_flow":     self.order_flow.get_dashboard_dict(),
            "event_calendar": self.event_calendar.get_dashboard_dict(),
            "combined": {
                "mod":      self.combined_modifier,
                "signal":   self.intel_signal,
                "bulls":    self.bull_count,
                "bears":    self.bear_count,
                "cautions": self.caution_flags,
            },
        }

    def __str__(self):
        lines = [
            f"Intelligence: {self.intel_signal} (mod={self.combined_modifier:+d})",
            f"  RegimeMemory : {self.regime_memory}",
            f"  SessionClock : {self.session_clock}",
            f"  OrderFlow    : {self.order_flow}",
            f"  EventCalendar: {self.event_calendar}",
        ]
        if self.caution_flags:
            lines.append(f"  ⚠ Cautions: {', '.join(self.caution_flags)}")
        return "\n".join(lines)


class IntelligenceBundle:
    """All four advanced intelligence engines in one bundle."""

    def __init__(self):
        self._regmem   = RegimeMemoryEngine()
        self._session  = SessionClockEngine()
        self._oflow    = OrderFlowEngine()
        self._calendar = EventCalendarEngine()
        self._loaded   = False

    def load_journal(self, source) -> int:
        """Load trade journal for regime memory. Call once at startup."""
        n = self._regmem.load(source)
        self._loaded = True
        return n

    def analyze(self,
                ticker:           str,
                bars:             list,
                daily_bars:       list           = None,
                regime:           str            = "MIXED",
                rvol:             float          = 1.5,
                score:            float          = 72.0,
                day_of_week:      Optional[int]  = None,
                pattern_name:     Optional[str]  = None,
                trade_direction:  str            = "long",
                today:            Optional[date] = None,
                current_hour_et:  int            = 10,
                current_minute:   int            = 0,
                blocklist:        Optional[set]  = None) -> IntelligenceResult:
        """Run all four engines and combine results."""
        today = today or date.today()
        td    = trade_direction.lower()

        # 1. Regime memory
        regmem = self._regmem.query(
            regime=regime, rvol=rvol, entry_hour=current_hour_et,
            score=score, day_of_week=day_of_week,
            pattern_name=pattern_name, blocklist=blocklist, ticker=ticker,
        ) if self._loaded else RegimeMemoryResult(note="journal not loaded")

        # 2. Session clock
        session = self._session.analyze(
            ticker=ticker, intraday_bars=bars,
            daily_bars=daily_bars or [], trade_direction=td,
            current_hour_et=current_hour_et, current_minute=current_minute,
        )

        # 3. Order flow
        oflow = self._oflow.analyze_bars(bars, td)

        # 4. Event calendar
        calendar = self._calendar.analyze(today)

        # Combine modifiers
        raw = (regmem.score_modifier + session.score_modifier +
               oflow.score_modifier  + calendar.score_modifier)
        combined = max(-COMBINED_CAP, min(COMBINED_CAP, raw))

        # Count bull/bear signals
        mods = [regmem.score_modifier, session.score_modifier,
                oflow.score_modifier,  calendar.score_modifier]
        bull_n = sum(1 for m in mods if m > 0)
        bear_n = sum(1 for m in mods if m < 0)

        # Collect caution flags
        cautions = []
        if calendar.is_fomc_day:   cautions.append("FOMC_DAY")
        if calendar.is_cpi_day:    cautions.append("CPI_DAY")
        if calendar.is_nfp_day:    cautions.append("NFP_DAY")
        if session.adr_signal == "DANGER":   cautions.append("ADR_DANGER")
        if session.adr_signal == "CAUTION":  cautions.append("ADR_CAUTION")
        if oflow.ofi_signal in ("STRONG_SELL","SELL") and td=="long":
            cautions.append("OFI_AGAINST_LONG")
        if regmem.regime_signal == "UNFAVORABLE":
            cautions.append("REGIME_MEMORY_UNFAVORABLE")

        # Overall signal
        if combined >= 10:    signal = "STRONG_BULLISH"
        elif combined >= 5:   signal = "BULLISH"
        elif combined <= -10: signal = "STRONG_BEARISH"
        elif combined <= -5:  signal = "BEARISH"
        else:                  signal = "NEUTRAL"

        result = IntelligenceResult(
            regime_memory  = regmem,
            session_clock  = session,
            order_flow     = oflow,
            event_calendar = calendar,
            combined_modifier = combined,
            intel_signal      = signal,
            bull_count        = bull_n,
            bear_count        = bear_n,
            caution_flags     = cautions,
        )

        logger.info("Intelligence: %s | mod=%+d | bulls=%d bears=%d cautions=%s",
                    signal, combined, bull_n, bear_n, cautions)
        return result


if __name__ == "__main__":
    import random
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("PMO Intelligence Bundle — smoke test\n")
    random.seed(42)

    def make_bars(n=30, bullish=True):
        bars, price = [], 210.0
        t = datetime(2026,6,16,9,30)
        import datetime as dt
        for i in range(n):
            move = random.uniform(0.1,0.3)*(1 if bullish else -1)
            o=price; c=price+move+random.gauss(0,.15)
            h=max(o,c)+.1; l=min(o,c)-.1
            bars.append({"open":round(o,2),"high":round(h,2),"low":round(l,2),
                         "close":round(c,2),"volume":100000,"datetime":t})
            price=c; t+=dt.timedelta(minutes=5)
        return bars

    def make_daily(n=10):
        bars, price = [], 208.0
        for i in range(n):
            h=price+random.uniform(1,3); l=price-random.uniform(1,3)
            bars.append({"open":price,"high":h,"low":l,"close":price+random.gauss(0,.5)})
            price=bars[-1]["close"]
        return bars

    # Synthetic trade history
    trades = []
    for i in range(60):
        r = random.choice(["BULL","MIXED","DEFENSIVE"])
        rvol = random.uniform(0.8,4.5)
        p_win = 0.7 if r=="BULL" else 0.45 if r=="MIXED" else 0.25
        won = random.random() < p_win
        trades.append({
            "ticker":"NVDA","score":round(random.uniform(65,85),1),
            "rvol":round(rvol,2),"pnl":round(random.uniform(.5,2.5) if won else random.uniform(-2.5,-.3),2),
            "outcome":"CLOSED_WIN" if won else "CLOSED_LOSS","regime":r,
            "entry_time":f"2026-0{random.randint(1,6)}-{random.randint(1,28):02d} 10:30:00",
        })

    bundle = IntelligenceBundle()
    bundle.load_journal(trades)

    result = bundle.analyze(
        ticker="NVDA", bars=make_bars(30,True),
        daily_bars=make_daily(10), regime="MIXED",
        rvol=2.3, score=72.0, trade_direction="long",
        today=date(2026,6,16), current_hour_et=10, current_minute=15,
    )
    print(result)
    print()
    print("Journal columns added:")
    jd = result.get_journal_dict()
    for k,v in jd.items():
        print(f"  {k:<28} {v}")

    print(f"\nTotal new journal columns: {len(jd)}")
    print(f"\n{INTELLIGENCE_SETTINGS}")
    print("Smoke test complete.")
