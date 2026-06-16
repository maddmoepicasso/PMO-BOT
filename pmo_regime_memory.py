"""
PMO Regime Memory Engine — pmo_regime_memory.py
================================================
Queries PMO's own trade journal to answer:
"What happened the last N times conditions were similar to right now?"

This is personalized backtesting running in real time.
No external data needed — uses your existing pmo_bot_trade_journal.csv.

Similarity dimensions:
  - Regime (BULL/MIXED/DEFENSIVE/BEAR)
  - RVOL bucket (<1.5, 1.5-2.5, 2.5+)
  - Entry hour bucket (open 9:30-10:30, mid 10:30-13:00, close 13:00-16:00)
  - Score band (65-74, 75-77, 78+)
  - Day of week
  - Pattern name (if available)

Output:
  historical_wr     : win rate in similar conditions
  historical_pf     : profit factor in similar conditions
  sample_size       : number of matching trades
  confidence        : LOW/MEDIUM/HIGH based on sample size
  regime_signal     : FAVORABLE / NEUTRAL / UNFAVORABLE
  score_modifier    : +5 / 0 / -4 (read-only until validated)
  best_condition    : what condition correlates most with wins
  worst_condition   : what condition correlates most with losses

Read-only: logged to journal, shown on dashboard.
Does NOT affect score until validated on 20+ similar-condition trades.
"""

import csv
import logging
import math
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger("pmo.regime_memory")

MIN_SAMPLE_CONFIDENT  = 15   # HIGH confidence
MIN_SAMPLE_MEDIUM     = 8    # MEDIUM confidence
MIN_SAMPLE_LOW        = 3    # LOW confidence (still useful directionally)

FAVORABLE_WR_THRESHOLD   = 0.55
UNFAVORABLE_WR_THRESHOLD = 0.40


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pnl(row):
    for k in ["pnl","profit_loss","realized_pnl","return_pct"]:
        v = row.get(k,"")
        if v not in (None,"","N/A"):
            try: return float(v)
            except: pass
    return 0.0

def _won(row):
    for k in ["outcome","result","trade_result","status"]:
        v = row.get(k,"").upper()
        if "WIN" in v or "PROFIT" in v: return True
        if "LOSS" in v or "LOSE"  in v: return False
    return _pnl(row) > 0

def _closed(rows):
    out = []
    for r in rows:
        for k in ["outcome","result","trade_result","status"]:
            v = r.get(k,"").upper()
            if any(x in v for x in ["CLOSED","WIN","LOSS"]):
                out.append(r); break
        else:
            if _pnl(r) != 0: out.append(r)
    return out

def _rvol_bucket(rvol: float) -> str:
    if rvol < 1.5:  return "low"
    if rvol < 2.5:  return "medium"
    return "high"

def _hour_bucket(hour: int) -> str:
    if hour < 10:   return "open"      # 9:30-10:00
    if hour < 13:   return "mid"       # 10:00-13:00
    return "close"                     # 13:00-16:00

def _score_band(score: float) -> str:
    if score < 65:  return "below"
    if score < 75:  return "65-74"
    if score < 78:  return "75-77"
    return "78+"

def _dow(dt_str: str) -> Optional[int]:
    for fmt in ["%Y-%m-%d %H:%M:%S","%Y-%m-%dT%H:%M:%S","%m/%d/%Y %H:%M"]:
        try:
            return datetime.strptime(dt_str[:19], fmt).weekday()
        except: pass
    return None

def _parse_float(v, default=0.0):
    try: return float(v)
    except: return default

def _parse_hour(row) -> Optional[int]:
    for k in ["entry_time","entry_datetime","open_time","time"]:
        v = str(row.get(k,""))
        if v:
            for fmt in ["%Y-%m-%d %H:%M:%S","%Y-%m-%dT%H:%M:%S"]:
                try: return datetime.strptime(v[:19], fmt).hour
                except: pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RegimeMemoryResult:
    historical_wr:    float = 0.5
    historical_pf:    float = 1.0
    sample_size:      int   = 0
    confidence:       str   = "NONE"
    regime_signal:    str   = "NEUTRAL"
    score_modifier:   int   = 0
    best_condition:   str   = ""
    worst_condition:  str   = ""
    match_criteria:   dict  = field(default_factory=dict)
    fallback_used:    bool  = False
    note:             str   = ""

    def get_journal_dict(self) -> dict:
        return {
            "regmem_wr":         round(self.historical_wr, 3),
            "regmem_pf":         round(self.historical_pf, 3),
            "regmem_n":          self.sample_size,
            "regmem_confidence": self.confidence,
            "regmem_signal":     self.regime_signal,
            "regmem_mod":        self.score_modifier,
            "regmem_best":       self.best_condition,
            "regmem_worst":      self.worst_condition,
        }

    def get_dashboard_dict(self) -> dict:
        return {
            "wr":         round(self.historical_wr * 100, 1),
            "pf":         round(self.historical_pf, 3),
            "n":          self.sample_size,
            "confidence": self.confidence,
            "signal":     self.regime_signal,
            "mod":        self.score_modifier,
            "best":       self.best_condition,
            "worst":      self.worst_condition,
            "note":       self.note,
            "criteria":   self.match_criteria,
        }

    def __str__(self):
        if self.sample_size == 0:
            return "RegimeMemory: no historical matches found"
        return (f"RegimeMemory: {self.regime_signal} | "
                f"WR={self.historical_wr*100:.1f}% PF={self.historical_pf:.2f} "
                f"n={self.sample_size} ({self.confidence}) | mod={self.score_modifier:+d} | "
                f"{self.note}")


# ─────────────────────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────────────────────

class RegimeMemoryEngine:
    """
    Queries PMO's own closed trade journal for historical performance
    under conditions similar to the current trade setup.

    engine = RegimeMemoryEngine()
    engine.load("pmo_bot_trade_journal.csv")
    result = engine.query(
        regime="MIXED",
        rvol=2.3,
        entry_hour=10,
        score=72.0,
        day_of_week=1,  # Tuesday
        pattern_name="Bull Flag",
        blocklist={"HOOD","PSQ","RWM","CVX"},
    )
    print(result)
    """

    def __init__(self):
        self._rows: list = []
        self._loaded: bool = False

    def load(self, source) -> int:
        """
        Load closed trades from CSV path or list of dicts.
        Returns number of usable closed trades loaded.
        """
        if isinstance(source, str):
            try:
                with open(source, newline="", encoding="utf-8-sig") as f:
                    rows = list(csv.DictReader(f))
            except FileNotFoundError:
                logger.warning("RegimeMemory: CSV not found: %s", source)
                return 0
        elif isinstance(source, list):
            rows = source
        else:
            return 0

        closed = _closed(rows)
        self._rows   = closed
        self._loaded = True
        logger.info("RegimeMemory: loaded %d closed trades", len(closed))
        return len(closed)

    def query(self,
              regime:       str             = "MIXED",
              rvol:         float           = 1.5,
              entry_hour:   int             = 10,
              score:        float           = 72.0,
              day_of_week:  Optional[int]   = None,
              pattern_name: Optional[str]   = None,
              blocklist:    Optional[set]   = None,
              ticker:       Optional[str]   = None) -> RegimeMemoryResult:
        """
        Query historical trades matching current conditions.
        Uses progressive relaxation: starts strict, loosens if too few matches.
        """
        bl = blocklist or {"HOOD","PSQ","RWM","CVX"}

        # Filter out blocked symbols
        pool = [r for r in self._rows
                if (r.get("ticker","") or r.get("symbol","")).upper() not in bl]

        if not pool:
            return RegimeMemoryResult(note="no clean trades in journal yet")

        # Build target condition buckets
        target = {
            "regime":     regime.upper(),
            "rvol_bkt":   _rvol_bucket(rvol),
            "hour_bkt":   _hour_bucket(entry_hour),
            "score_bnd":  _score_band(score),
            "dow":        day_of_week,
            "pattern":    (pattern_name or "").strip() or None,
        }

        # Progressive relaxation: try strict → medium → loose
        levels = [
            # (label, required_keys)
            ("strict",  ["regime","rvol_bkt","hour_bkt","score_bnd"]),
            ("medium",  ["regime","rvol_bkt","hour_bkt"]),
            ("loose",   ["regime","rvol_bkt"]),
            ("regime",  ["regime"]),
        ]

        matched = []
        used_level = "none"
        used_keys  = []

        for level_name, keys in levels:
            candidates = self._filter(pool, target, keys)
            if len(candidates) >= MIN_SAMPLE_LOW:
                matched    = candidates
                used_level = level_name
                used_keys  = keys
                break

        if not matched:
            # Use full pool as fallback
            matched    = pool
            used_level = "full_pool"
            used_keys  = []

        fallback = used_level in ("regime","full_pool")
        result   = self._compute(matched, target, used_keys, fallback)
        result.match_criteria = {k: target[k] for k in used_keys if target.get(k)}
        result.note = (f"matched {len(matched)} trades at '{used_level}' level "
                       f"on {used_keys}" if used_keys else
                       f"using full pool ({len(matched)} trades) — too few specific matches")
        return result

    def _filter(self, pool: list, target: dict, keys: list) -> list:
        """Filter pool to rows matching target on the given keys."""
        out = []
        for row in pool:
            match = True
            for key in keys:
                tv = target.get(key)
                if tv is None:
                    continue
                rv = self._extract(row, key)
                if rv != tv:
                    match = False
                    break
            if match:
                out.append(row)
        return out

    def _extract(self, row: dict, key: str):
        """Extract the bucketed value for a given key from a trade row."""
        if key == "regime":
            v = str(row.get("regime") or row.get("market_regime","")).upper()
            return v if v else None
        if key == "rvol_bkt":
            v = _parse_float(row.get("rvol") or row.get("relative_volume",""), 0)
            return _rvol_bucket(v) if v > 0 else None
        if key == "hour_bkt":
            h = _parse_hour(row)
            return _hour_bucket(h) if h is not None else None
        if key == "score_bnd":
            v = _parse_float(row.get("score") or row.get("pmo_score",""), 0)
            return _score_band(v) if v > 0 else None
        if key == "dow":
            for k in ["entry_time","entry_datetime","open_time"]:
                dv = str(row.get(k,""))
                if dv:
                    d = _dow(dv)
                    if d is not None: return d
            return None
        if key == "pattern":
            return str(row.get("pattern_name","")).strip() or None
        return None

    def _compute(self, rows: list, target: dict,
                 used_keys: list, fallback: bool) -> RegimeMemoryResult:
        """Compute stats on matched rows."""
        wins   = [r for r in rows if _won(r)]
        losses = [r for r in rows if not _won(r)]
        n      = len(rows)

        if n == 0:
            return RegimeMemoryResult()

        wr = len(wins) / n
        wpnls = [_pnl(r) for r in wins]
        lpnls = [_pnl(r) for r in losses]
        gw = sum(wpnls)
        gl = abs(sum(lpnls))
        pf = round(gw / gl, 3) if gl > 0 else 999.0

        # Confidence
        if n >= MIN_SAMPLE_CONFIDENT and not fallback:
            confidence = "HIGH"
        elif n >= MIN_SAMPLE_MEDIUM and not fallback:
            confidence = "MEDIUM"
        elif n >= MIN_SAMPLE_LOW:
            confidence = "LOW"
        else:
            confidence = "VERY_LOW"

        # Signal
        if wr >= FAVORABLE_WR_THRESHOLD and not fallback:
            signal   = "FAVORABLE"
            modifier = +5
        elif wr <= UNFAVORABLE_WR_THRESHOLD and not fallback:
            signal   = "UNFAVORABLE"
            modifier = -4
        else:
            signal   = "NEUTRAL"
            modifier = 0

        # Best/worst sub-conditions
        best  = self._best_subcondition(rows, target)
        worst = self._worst_subcondition(rows, target)

        return RegimeMemoryResult(
            historical_wr   = round(wr, 4),
            historical_pf   = pf,
            sample_size     = n,
            confidence      = confidence,
            regime_signal   = signal,
            score_modifier  = modifier,
            best_condition  = best,
            worst_condition = worst,
            fallback_used   = fallback,
        )

    def _best_subcondition(self, rows: list, target: dict) -> str:
        """Find the sub-condition with the highest win rate."""
        if len(rows) < 4:
            return ""
        # Check day of week
        dow_stats = {}
        for r in rows:
            for k in ["entry_time","entry_datetime"]:
                dv = str(r.get(k,""))
                if dv:
                    d = _dow(dv)
                    if d is not None:
                        if d not in dow_stats:
                            dow_stats[d] = [0,0]
                        dow_stats[d][0] += 1
                        if _won(r): dow_stats[d][1] += 1
                        break
        if dow_stats:
            days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
            best_d = max(dow_stats, key=lambda d: dow_stats[d][1]/max(dow_stats[d][0],1))
            if dow_stats[best_d][0] >= 2 and 0 <= best_d < len(days):
                bwr = dow_stats[best_d][1]/dow_stats[best_d][0]*100
                return f"{days[best_d]} ({bwr:.0f}% WR, n={dow_stats[best_d][0]})"
        return ""

    def _worst_subcondition(self, rows: list, target: dict) -> str:
        """Find the sub-condition with the lowest win rate."""
        if len(rows) < 4:
            return ""
        dow_stats = {}
        for r in rows:
            for k in ["entry_time","entry_datetime"]:
                dv = str(r.get(k,""))
                if dv:
                    d = _dow(dv)
                    if d is not None:
                        if d not in dow_stats:
                            dow_stats[d] = [0,0]
                        dow_stats[d][0] += 1
                        if _won(r): dow_stats[d][1] += 1
                        break
        if dow_stats:
            days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
            worst_d = min(dow_stats, key=lambda d: dow_stats[d][1]/max(dow_stats[d][0],1))
            if dow_stats[worst_d][0] >= 2 and 0 <= worst_d < len(days):
                bwr = dow_stats[worst_d][1]/dow_stats[worst_d][0]*100
                return f"{days[worst_d]} ({bwr:.0f}% WR, n={dow_stats[worst_d][0]})"
        return ""

    def summary(self) -> dict:
        """Full performance breakdown by regime, rvol, hour, score band."""
        if not self._rows:
            return {}
        out = {}
        for dim, fn in [
            ("regime",     lambda r: str(r.get("regime","")).upper() or "UNKNOWN"),
            ("rvol_bucket",lambda r: _rvol_bucket(_parse_float(r.get("rvol",""),0))),
            ("hour_bucket",lambda r: _hour_bucket(_parse_hour(r) or 11)),
            ("score_band", lambda r: _score_band(_parse_float(r.get("score",""),72))),
        ]:
            buckets = {}
            for row in self._rows:
                k = fn(row)
                if k not in buckets: buckets[k] = [0,0,0.0,0.0]
                buckets[k][0] += 1
                if _won(row): buckets[k][1] += 1
                p = _pnl(row)
                if p > 0: buckets[k][2] += p
                else:     buckets[k][3] += abs(p)
            result = {}
            for k, (n,w,gw,gl) in buckets.items():
                result[k] = {
                    "n": n, "wins": w, "losses": n-w,
                    "wr": round(w/n*100,1) if n else 0,
                    "pf": round(gw/gl,3) if gl else 999.0,
                }
            out[dim] = result
        return out


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import random, datetime, tempfile, os
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("PMO Regime Memory Engine — smoke test\n")
    random.seed(42)

    regimes = ["BULL","MIXED","DEFENSIVE","MIXED","BULL","BULL","MIXED","DEFENSIVE"]
    days    = ["Mon","Tue","Wed","Thu","Fri"]

    rows = []
    for i in range(89):
        regime = regimes[i % len(regimes)]
        rvol   = random.uniform(0.8, 4.5)
        score  = random.uniform(65, 88)
        hour   = random.choice([9,10,10,11,12,13,14])
        dow    = i % 5
        p_win  = (0.70 if regime=="BULL" else 0.45 if regime=="MIXED" else 0.30)
        p_win += (rvol - 2.0) * 0.05
        p_win  = max(0.1, min(0.9, p_win))
        won    = random.random() < p_win
        pnl    = random.uniform(0.5,3.0) if won else random.uniform(-2.5,-0.3)
        dt     = datetime.datetime(2026,1,2,hour,30) + datetime.timedelta(days=i*3)
        rows.append({
            "ticker":   random.choice(["NVDA","AAPL","TSLA","META","AMD","MSFT"]),
            "score":    round(score,1),
            "rvol":     round(rvol,2),
            "pnl":      round(pnl,2),
            "outcome":  "CLOSED_WIN" if won else "CLOSED_LOSS",
            "regime":   regime,
            "entry_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "pattern_name": random.choice(["Bull Flag","None","Double Bottom","None","Bear Flag"]),
        })

    engine = RegimeMemoryEngine()
    engine.load(rows)

    print("=== Query: BULL regime, RVOL 2.3, 10am, score 72 ===")
    r = engine.query(regime="BULL", rvol=2.3, entry_hour=10, score=72.0, day_of_week=1)
    print(f"  {r}")
    print(f"  Journal: {r.get_journal_dict()}")

    print()
    print("=== Query: MIXED regime, RVOL 1.2, 14pm, score 76 ===")
    r2 = engine.query(regime="MIXED", rvol=1.2, entry_hour=14, score=76.0)
    print(f"  {r2}")

    print()
    print("=== Query: DEFENSIVE regime ===")
    r3 = engine.query(regime="DEFENSIVE", rvol=2.0, entry_hour=11, score=70.0)
    print(f"  {r3}")

    print()
    print("=== Summary breakdown ===")
    summary = engine.summary()
    for dim, buckets in summary.items():
        print(f"\n  {dim}:")
        for k, stats in sorted(buckets.items()):
            print(f"    {k:<12} n={stats['n']:>3} WR={stats['wr']:>5.1f}% PF={stats['pf']:.3f}")

    print("\nSmoke test complete.")
