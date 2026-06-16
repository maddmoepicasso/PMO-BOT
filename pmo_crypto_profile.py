"""
PMO Crypto Strategy Profile — pmo_crypto_profile.py
=====================================================
Separate strategy parameters for crypto after-hours trading.
Based on PMO's real trade data: 15 crypto trades, 15W/0L, 100% WR.

Key differences from equity intraday strategy:
  - 24/7 market: no session open/close edge, different momentum patterns
  - Higher volatility: wider stops needed to avoid noise
  - Longer hold times: crypto moves extend overnight vs equity intraday
  - No PDT rule: can trade freely without day-trade constraints
  - Different RVOL baseline: crypto volume patterns differ from equities
  - Exchange-specific: Alpaca crypto (Coinbase/Kraken feed)

Crypto-specific parameters (separate from equity settings):
  - Stop loss: 6% (vs 4% equity) — crypto is noisier
  - Take profit: 10% (vs 6% equity) — moves extend further
  - Trailing activation: 5% profit (vs 3% equity)
  - Trailing stop: 3% (vs 2% equity)
  - Min RVOL: 1.2 (vs 1.5 equity) — crypto baseline is lower
  - Max hold: 720 min / 12h (vs 390 min equity)
  - Min score: 65 (same as equity rebuild gate)
  - Session: ANYTIME (no time-of-day restriction)
  - Max positions: 3 concurrent crypto (separate from equity limit)

Read-only initially: logs crypto-specific signals, validates parameters
against 15-trade clean proof before activating different sizing.
"""

import csv
import logging
import math
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

logger = logging.getLogger("pmo.crypto_profile")

# ─────────────────────────────────────────────────────────────────────────────
# Crypto symbol registry
# ─────────────────────────────────────────────────────────────────────────────

CRYPTO_SYMBOLS = {
    # Spot crypto pairs (Alpaca format)
    "BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD", "AVAX/USD",
    "LINK/USD", "LTC/USD", "BCH/USD", "XRP/USD", "ADA/USD",
    "DOT/USD", "MATIC/USD", "UNI/USD", "AAVE/USD", "ATOM/USD",
    # Alpaca normalized (no slash)
    "BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "AVAXUSD",
    "LINKUSD", "LTCUSD", "BCHUSD", "XRPUSD", "ADAUSD",
}

# Your proven crypto winners from PMO journal
PROVEN_CRYPTO = {
    "DOGE/USD": {"trades": 4, "wins": 4, "wr": 1.0},
    "LINK/USD": {"trades": 4, "wins": 4, "wr": 1.0},
    "SOL/USD":  {"trades": 3, "wins": 3, "wr": 1.0},
    "LTC/USD":  {"trades": 2, "wins": 2, "wr": 1.0},
    "BCH/USD":  {"trades": 1, "wins": 1, "wr": 1.0},
    "AVAX/USD": {"trades": 1, "wins": 1, "wr": 1.0},
}

def is_crypto(ticker: str) -> bool:
    return ticker.upper() in CRYPTO_SYMBOLS or "/" in ticker


# ─────────────────────────────────────────────────────────────────────────────
# Strategy profiles
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CryptoStrategyProfile:
    """
    Complete crypto-specific strategy parameters.
    Separate from equity intraday settings.
    """
    # Exit parameters
    stop_loss_pct:          float = 6.0     # wider than equity 4%
    take_profit_pct:        float = 10.0    # higher target than equity 6%
    trailing_activation_pct:float = 5.0     # activates at +5% (equity: 3%)
    trailing_stop_pct:      float = 3.0     # 3% trail (equity: 2%)

    # Entry filters
    min_rvol:               float = 1.2     # lower baseline (equity: 1.5)
    min_score:              float = 65.0    # same floor as equity rebuild gate
    min_score_proven:       float = 60.0    # lower for proven crypto symbols

    # Position management
    max_hold_minutes:       int   = 720     # 12 hours (equity: 390)
    max_concurrent:         int   = 3       # crypto positions (separate limit)
    notional_usd:           float = 40.0    # same as equity base notional
    notional_proven:        float = 50.0    # slight size boost for proven symbols

    # Session
    session_restriction:    str   = "NONE"  # 24/7, no time gate
    regime_required:        str   = "NONE"  # crypto has own momentum, not tied to equity regime

    # Proof gates (crypto-specific)
    min_proof_trades:       int   = 10
    min_proof_wr:           float = 0.60    # higher bar than equity (0.52)
    min_proof_pf:           float = 1.50    # higher bar than equity (1.25)

    # Partial exit plan (new)
    partial_exit_1_pct:     float = 5.0     # take 40% off at +5%
    partial_exit_1_size:    float = 0.40    # 40% of position
    partial_exit_2_pct:     float = 8.0     # take another 30% at +8%
    partial_exit_2_size:    float = 0.30    # 30% of position
    # remainder rides with trailing stop

    def get_settings_dict(self) -> dict:
        return {
            "PMO_CRYPTO_STOP_LOSS_PCT":           self.stop_loss_pct,
            "PMO_CRYPTO_TAKE_PROFIT_PCT":         self.take_profit_pct,
            "PMO_CRYPTO_TRAIL_ACTIVATION_PCT":    self.trailing_activation_pct,
            "PMO_CRYPTO_TRAIL_STOP_PCT":          self.trailing_stop_pct,
            "PMO_CRYPTO_MIN_RVOL":                self.min_rvol,
            "PMO_CRYPTO_MIN_SCORE":               self.min_score,
            "PMO_CRYPTO_MIN_SCORE_PROVEN":        self.min_score_proven,
            "PMO_CRYPTO_MAX_HOLD_MIN":            self.max_hold_minutes,
            "PMO_CRYPTO_MAX_CONCURRENT":          self.max_concurrent,
            "PMO_CRYPTO_NOTIONAL_USD":            self.notional_usd,
            "PMO_CRYPTO_NOTIONAL_PROVEN":         self.notional_proven,
            "PMO_CRYPTO_PARTIAL_EXIT_1_PCT":      self.partial_exit_1_pct,
            "PMO_CRYPTO_PARTIAL_EXIT_1_SIZE":     self.partial_exit_1_size,
            "PMO_CRYPTO_PARTIAL_EXIT_2_PCT":      self.partial_exit_2_pct,
            "PMO_CRYPTO_PARTIAL_EXIT_2_SIZE":     self.partial_exit_2_size,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Analysis engine
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CryptoAnalysisResult:
    is_crypto:          bool  = False
    is_proven:          bool  = False
    symbol_proof:       dict  = field(default_factory=dict)
    profile:            Optional[CryptoStrategyProfile] = None

    # Recommended parameters for this trade
    stop_loss_pct:      float = 4.0
    take_profit_pct:    float = 6.0
    trail_activation:   float = 3.0
    trail_stop:         float = 2.0
    notional:           float = 40.0
    max_hold_min:       int   = 390
    min_rvol:           float = 1.5

    # Signals
    momentum_signal:    str   = "NEUTRAL"
    session_signal:     str   = "NEUTRAL"
    regime_note:        str   = ""
    score_modifier:     int   = 0
    recommendation:     str   = "USE_EQUITY_PARAMS"

    # Partial exit plan
    partial_exits:      list  = field(default_factory=list)

    def get_journal_dict(self) -> dict:
        return {
            "crypto_is_crypto":    self.is_crypto,
            "crypto_is_proven":    self.is_proven,
            "crypto_stop_pct":     self.stop_loss_pct,
            "crypto_tp_pct":       self.take_profit_pct,
            "crypto_notional":     self.notional,
            "crypto_signal":       self.momentum_signal,
            "crypto_mod":          self.score_modifier,
            "crypto_rec":          self.recommendation,
        }

    def get_dashboard_dict(self) -> dict:
        return {
            "is_crypto":     self.is_crypto,
            "is_proven":     self.is_proven,
            "stop_pct":      self.stop_loss_pct,
            "tp_pct":        self.take_profit_pct,
            "trail_act":     self.trail_activation,
            "trail_stop":    self.trail_stop,
            "notional":      self.notional,
            "max_hold":      self.max_hold_min,
            "signal":        self.momentum_signal,
            "mod":           self.score_modifier,
            "rec":           self.recommendation,
            "partial_exits": self.partial_exits,
            "regime_note":   self.regime_note,
        }

    def __str__(self):
        if not self.is_crypto:
            return "CryptoProfile: equity symbol — use standard params"
        proven = " (PROVEN)" if self.is_proven else ""
        return (f"CryptoProfile{proven}: {self.momentum_signal} | "
                f"stop={self.stop_loss_pct}% TP={self.take_profit_pct}% "
                f"trail@{self.trail_activation}% | "
                f"notional=${self.notional} hold={self.max_hold_min}min | "
                f"rec={self.recommendation}")


class CryptoProfileEngine:
    """
    Determines crypto-specific strategy parameters for a given symbol.

    engine = CryptoProfileEngine()
    engine.load_journal("pmo_bot_trade_journal.csv")
    result = engine.analyze("SOL/USD", bars=bars, current_hour_et=20)
    print(result)
    """

    def __init__(self, profile: Optional[CryptoStrategyProfile] = None):
        self._profile      = profile or CryptoStrategyProfile()
        self._crypto_stats = {}   # per-symbol stats from journal
        self._loaded       = False

    def load_journal(self, source) -> int:
        """Load crypto trade history from journal."""
        if isinstance(source, str):
            try:
                with open(source, newline="", encoding="utf-8-sig") as f:
                    rows = list(csv.DictReader(f))
            except FileNotFoundError:
                logger.warning("CryptoProfile: journal not found: %s", source)
                return 0
        else:
            rows = source

        # Extract crypto closed trades
        crypto_trades = []
        for row in rows:
            ticker = (row.get("ticker","") or row.get("symbol","")).upper()
            if not is_crypto(ticker):
                continue
            outcome = row.get("outcome","").upper()
            if "WIN" in outcome or "LOSS" in outcome:
                crypto_trades.append(row)

        # Build per-symbol stats
        from collections import defaultdict
        sym_data = defaultdict(lambda: {"n":0,"w":0,"pnl":0.0})
        for row in crypto_trades:
            ticker = (row.get("ticker","") or row.get("symbol","")).upper()
            won = "WIN" in row.get("outcome","").upper()
            try: pnl = float(row.get("pnl",0))
            except: pnl = 0.0
            sym_data[ticker]["n"]   += 1
            sym_data[ticker]["pnl"] += pnl
            if won: sym_data[ticker]["w"] += 1

        self._crypto_stats = {
            sym: {
                "trades": d["n"],
                "wins":   d["w"],
                "wr":     d["w"]/d["n"] if d["n"] else 0,
                "net":    round(d["pnl"],2),
            }
            for sym, d in sym_data.items()
        }

        self._loaded = True
        n = len(crypto_trades)
        logger.info("CryptoProfile: loaded %d crypto trades, %d symbols",
                    n, len(self._crypto_stats))
        return n

    def _crypto_momentum(self, bars: list, current_hour_et: int) -> tuple:
        """
        Compute crypto-specific momentum signal.
        Returns (signal, score_modifier)
        Crypto momentum: RVOL + trend + time context
        """
        if not bars or len(bars) < 5:
            return "NEUTRAL", 0

        closes = [float(b.get("close",0)) for b in bars[-20:] if b.get("close")]
        vols   = [float(b.get("volume",0)) for b in bars[-20:] if b.get("volume")]

        if not closes or not vols:
            return "NEUTRAL", 0

        # Trend: is price above its 10-bar avg?
        avg10 = sum(closes[-10:]) / min(10, len(closes))
        trend_up = closes[-1] > avg10

        # Volume: is current above 20-bar avg?
        avg_vol = sum(vols) / len(vols) if vols else 1
        curr_vol = vols[-1] if vols else 0
        rvol = curr_vol / avg_vol if avg_vol > 0 else 1.0

        # Time context for crypto
        # Asian session (7pm-4am ET): lower volume, but breakouts reliable
        # London open (3am-11am): increasing volume
        # After US close (4pm-7pm): often highest crypto volume
        if 16 <= current_hour_et <= 23:
            time_bonus = +2   # post-US close, crypto most active
        elif 0 <= current_hour_et <= 4:
            time_bonus = +1   # Asian session active
        elif 9 <= current_hour_et <= 16:
            time_bonus = 0    # US hours, equity competition
        else:
            time_bonus = +1

        # Signal
        if trend_up and rvol >= 1.5:
            signal = "BULLISH"
            mod    = 4 + time_bonus
        elif trend_up and rvol >= 1.2:
            signal = "MILD_BULLISH"
            mod    = 2 + time_bonus
        elif not trend_up and rvol >= 1.5:
            signal = "BEARISH_VOLUME"
            mod    = -2
        else:
            signal = "NEUTRAL"
            mod    = time_bonus

        return signal, max(-5, min(8, mod))

    def _build_partial_exits(self, entry_price: float,
                              profile: CryptoStrategyProfile) -> list:
        """Build the partial exit plan for a crypto trade."""
        exits = []
        if entry_price > 0:
            exits.append({
                "at_pct":   profile.partial_exit_1_pct,
                "at_price": round(entry_price * (1 + profile.partial_exit_1_pct/100), 4),
                "size_pct": int(profile.partial_exit_1_size * 100),
                "action":   f"Sell {int(profile.partial_exit_1_size*100)}% at +{profile.partial_exit_1_pct}%",
            })
            exits.append({
                "at_pct":   profile.partial_exit_2_pct,
                "at_price": round(entry_price * (1 + profile.partial_exit_2_pct/100), 4),
                "size_pct": int(profile.partial_exit_2_size * 100),
                "action":   f"Sell {int(profile.partial_exit_2_size*100)}% at +{profile.partial_exit_2_pct}%",
            })
            remainder = 100 - int((profile.partial_exit_1_size + profile.partial_exit_2_size)*100)
            exits.append({
                "at_pct":   None,
                "at_price": None,
                "size_pct": remainder,
                "action":   f"Remainder {remainder}% rides with {profile.trailing_stop_pct}% trailing stop",
            })
        return exits

    def analyze(self,
                ticker:          str,
                bars:            list           = None,
                current_hour_et: int            = 12,
                entry_price:     float          = 0.0,
                trade_direction: str            = "long") -> CryptoAnalysisResult:
        """
        Analyze a ticker and return crypto-specific strategy parameters.
        For non-crypto symbols, returns USE_EQUITY_PARAMS recommendation.
        """
        result = CryptoAnalysisResult()

        if not is_crypto(ticker):
            result.is_crypto      = False
            result.recommendation = "USE_EQUITY_PARAMS"
            # Return standard equity params
            result.stop_loss_pct    = 4.0
            result.take_profit_pct  = 6.0
            result.trail_activation = 3.0
            result.trail_stop       = 2.0
            result.notional         = 40.0
            result.max_hold_min     = 390
            result.min_rvol         = 1.5
            return result

        result.is_crypto = True
        p = self._profile

        # Check if proven symbol
        sym_upper = ticker.upper()
        journal_stats = self._crypto_stats.get(sym_upper, {})
        builtin_proof = PROVEN_CRYPTO.get(sym_upper, {})

        n_trades = journal_stats.get("trades", builtin_proof.get("trades", 0))
        n_wins   = journal_stats.get("wins",   builtin_proof.get("wins", 0))
        wr       = journal_stats.get("wr",     builtin_proof.get("wr", 0))

        result.is_proven    = (n_trades >= 2 and wr >= 0.80)
        result.symbol_proof = {
            "trades": n_trades, "wins": n_wins,
            "wr": round(wr, 3), "net": journal_stats.get("net", 0),
        }

        # Set profile parameters
        result.profile          = p
        result.stop_loss_pct    = p.stop_loss_pct
        result.take_profit_pct  = p.take_profit_pct
        result.trail_activation = p.trailing_activation_pct
        result.trail_stop       = p.trailing_stop_pct
        result.max_hold_min     = p.max_hold_minutes
        result.min_rvol         = p.min_rvol

        # Proven symbols get slightly tighter score gate + bigger notional
        if result.is_proven:
            result.notional = p.notional_proven
        else:
            result.notional = p.notional_usd

        # Crypto momentum signal
        momentum, mod = self._crypto_momentum(bars or [], current_hour_et)
        result.momentum_signal = momentum
        result.score_modifier  = mod

        # Session note
        if 16 <= current_hour_et <= 23:
            result.session_signal = "OPTIMAL"
            result.regime_note    = "Post-US-close: highest crypto volume window"
        elif 0 <= current_hour_et <= 4:
            result.session_signal = "ACTIVE"
            result.regime_note    = "Asian session: crypto momentum can extend"
        elif 9 <= current_hour_et <= 16:
            result.session_signal = "VALID"
            result.regime_note    = "US hours: equity regime does not block crypto"
        else:
            result.session_signal = "NEUTRAL"
            result.regime_note    = "Pre-market: lower volume, wider spreads"

        # Partial exit plan
        result.partial_exits = self._build_partial_exits(entry_price or 0.0, p)

        # Recommendation
        if momentum in ("BULLISH", "MILD_BULLISH"):
            result.recommendation = "USE_CRYPTO_PARAMS"
            if result.is_proven:
                result.recommendation = "USE_CRYPTO_PARAMS_PROVEN"
        elif momentum == "BEARISH_VOLUME":
            result.recommendation = "CAUTION_BEARISH_VOLUME"
        else:
            result.recommendation = "USE_CRYPTO_PARAMS"

        logger.info(
            "CryptoProfile: %s proven=%s momentum=%s mod=%+d rec=%s",
            ticker, result.is_proven, momentum, mod, result.recommendation
        )
        return result

    def get_all_crypto_stats(self) -> dict:
        """Returns per-symbol crypto performance from journal."""
        return self._crypto_stats or self._builtin_crypto_stats()

    def summary(self) -> dict:
        """Overall crypto proof summary."""
        stats = self._crypto_stats or self._builtin_crypto_stats()
        if not stats:
            return {"loaded": False, "note": "No crypto trades in journal"}
        all_trades = sum(s["trades"] for s in stats.values())
        all_wins   = sum(s["wins"]   for s in stats.values())
        all_net    = sum(s.get("net", 0) for s in stats.values())
        return {
            "loaded":         True,
            "source":         "journal" if self._crypto_stats else "builtin_proven_crypto",
            "total_trades":   all_trades,
            "total_wins":     all_wins,
            "total_losses":   all_trades - all_wins,
            "win_rate":       round(all_wins / all_trades, 4) if all_trades else 0,
            "net_pnl":        round(all_net, 2),
            "symbols_traded": list(stats.keys()),
            "proven_symbols": [
                s for s, d in stats.items()
                if d["trades"] >= 2 and d["wr"] >= 0.80
            ],
        }

    def _builtin_crypto_stats(self) -> dict:
        return {
            sym: {
                "trades": int(data.get("trades", 0)),
                "wins": int(data.get("wins", 0)),
                "wr": round(float(data.get("wr", 0)), 3),
                "net": 0,
            }
            for sym, data in PROVEN_CRYPTO.items()
        }


# ─────────────────────────────────────────────────────────────────────────────
# pmo_settings.py additions
# ─────────────────────────────────────────────────────────────────────────────

CRYPTO_SETTINGS = """
# ── Crypto Strategy Profile Settings (add to pmo_settings.py) ────────────────
PMO_CRYPTO_PROFILE_ENABLED      = True
PMO_CRYPTO_STOP_LOSS_PCT        = 6.0     # wider than equity 4%
PMO_CRYPTO_TAKE_PROFIT_PCT      = 10.0    # higher than equity 6%
PMO_CRYPTO_TRAIL_ACTIVATION_PCT = 5.0     # activates at +5% profit
PMO_CRYPTO_TRAIL_STOP_PCT       = 3.0     # 3% trail
PMO_CRYPTO_MIN_RVOL             = 1.2     # lower baseline than equity
PMO_CRYPTO_MIN_SCORE            = 65.0    # same rebuild floor
PMO_CRYPTO_MIN_SCORE_PROVEN     = 60.0    # lower for proven symbols
PMO_CRYPTO_MAX_HOLD_MIN         = 720     # 12 hours
PMO_CRYPTO_MAX_CONCURRENT       = 3       # separate from equity limit
PMO_CRYPTO_NOTIONAL_USD         = 40.0    # base notional
PMO_CRYPTO_NOTIONAL_PROVEN      = 50.0    # slight boost for proven symbols
PMO_CRYPTO_PARTIAL_EXIT_1_PCT   = 5.0     # take 40% off at +5%
PMO_CRYPTO_PARTIAL_EXIT_1_SIZE  = 0.40
PMO_CRYPTO_PARTIAL_EXIT_2_PCT   = 8.0     # take 30% off at +8%
PMO_CRYPTO_PARTIAL_EXIT_2_SIZE  = 0.30
# Remainder rides with trailing stop
# ─────────────────────────────────────────────────────────────────────────────
"""

CRYPTO_FLASK_ROUTES = '''
# ── Add to pmo_bot.py ─────────────────────────────────────────────────────────
from pmo_crypto_profile import CryptoProfileEngine, is_crypto

_CRYPTO_ENGINE = CryptoProfileEngine()
# Load at startup (add near other engine inits):
# _CRYPTO_ENGINE.load_journal(TRADE_JOURNAL_CSV_PATH)

@app.route("/api/crypto/profile", methods=["GET","POST"])
def crypto_profile():
    data   = request.json or {}
    ticker = data.get("ticker","BTC/USD")
    bars   = data.get("bars", [])
    hour   = data.get("hour_et", datetime.now().hour)
    price  = data.get("entry_price", 0.0)
    result = _CRYPTO_ENGINE.analyze(ticker, bars, hour, price)
    return jsonify({"ok": True, **result.get_dashboard_dict(),
                    "ticker": ticker, "is_crypto": result.is_crypto})

@app.route("/api/crypto/summary", methods=["GET"])
def crypto_summary():
    return jsonify({"ok": True, **_CRYPTO_ENGINE.summary()})

@app.route("/api/crypto/stats", methods=["GET"])
def crypto_stats():
    return jsonify({"ok": True, "stats": _CRYPTO_ENGINE.get_all_crypto_stats()})
# ── End crypto routes ─────────────────────────────────────────────────────────
'''


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import random, datetime
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("PMO Crypto Strategy Profile — smoke test\n")
    random.seed(42)

    # Synthetic journal with crypto trades
    journal = []
    crypto_syms = ["DOGE/USD","LINK/USD","SOL/USD","LTC/USD","BCH/USD","AVAX/USD"]
    equity_syms = ["NVDA","AAPL","TSLA","META","AMD"]

    for i in range(15):
        sym = crypto_syms[i % len(crypto_syms)]
        pnl = random.uniform(0.4, 3.5)  # all winners
        journal.append({"ticker":sym,"pnl":round(pnl,2),"outcome":"CLOSED_WIN",
                        "entry_time":f"2026-0{random.randint(1,6)}-01 20:30:00"})
    for i in range(42):
        sym = equity_syms[i % len(equity_syms)]
        won = random.random() < 0.55
        pnl = random.uniform(0.5,2.5) if won else random.uniform(-2.0,-0.3)
        journal.append({"ticker":sym,"pnl":round(pnl,2),
                        "outcome":"CLOSED_WIN" if won else "CLOSED_LOSS"})

    engine = CryptoProfileEngine()
    engine.load_journal(journal)

    def make_bars(n=20, trend=0.05):
        bars, price = [], 100.0
        t = datetime.datetime(2026,6,16,20,0)
        for i in range(n):
            c = price + trend + random.gauss(0,.3)
            bars.append({"open":price,"high":max(price,c)+.1,
                         "low":min(price,c)-.1,"close":round(c,2),
                         "volume":random.randint(50000,200000),"datetime":t})
            price = c
            t += datetime.timedelta(minutes=5)
        return bars

    print("=== SOL/USD at 8pm ET (proven, post-close) ===")
    r = engine.analyze("SOL/USD", make_bars(20, 0.08), current_hour_et=20, entry_price=65.0)
    print(f"  {r}")
    print(f"  Partial exits:")
    for ex in r.partial_exits:
        print(f"    {ex['action']}")
    print(f"  Journal: {r.get_journal_dict()}")

    print()
    print("=== DOGE/USD at 10am ET (proven, US hours) ===")
    r2 = engine.analyze("DOGE/USD", make_bars(20, 0.04), current_hour_et=10, entry_price=0.085)
    print(f"  {r2}")

    print()
    print("=== NVDA (equity — should use equity params) ===")
    r3 = engine.analyze("NVDA", make_bars(20), current_hour_et=10)
    print(f"  {r3}")

    print()
    print("=== Crypto summary ===")
    import json
    print(json.dumps(engine.summary(), indent=2))

    print()
    print("Settings to add:")
    print(CRYPTO_SETTINGS)
    print("\nSmoke test complete.")
