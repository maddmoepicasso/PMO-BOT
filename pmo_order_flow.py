"""
PMO Order Flow Imbalance Engine — pmo_order_flow.py
=====================================================
Detects aggressive buying/selling pressure from bid-ask quote data.
Uses Alpaca quote feed (free tier available).

Order flow imbalance (OFI) = difference between buy-side and sell-side
aggressive order volume. When buyers are lifting the ask repeatedly,
OFI is positive. When sellers are hitting the bid, OFI is negative.

Also computes:
  - Bid-ask spread trend (widening = uncertainty, narrowing = conviction)
  - Quote stuffing detection (abnormally high quote rate = noise)
  - Cumulative delta proxy from bar close positions
  - Volume-weighted pressure score

Free data: Alpaca /v2/stocks/{symbol}/quotes/latest (no subscription needed)
Bars-based proxy: uses bar close vs midpoint as OFI approximation when
quote data is unavailable (works on free Alpaca tier).

Read-only: logged, shown on dashboard, does NOT affect score until validated.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("pmo.order_flow")

# OFI score thresholds
OFI_STRONG_BULL  =  0.60   # >60% buy pressure
OFI_WEAK_BULL    =  0.55
OFI_NEUTRAL_HIGH =  0.55
OFI_NEUTRAL_LOW  =  0.45
OFI_WEAK_BEAR    =  0.45
OFI_STRONG_BEAR  =  0.40   # <40% buy pressure

SPREAD_WIDENING_THRESHOLD = 1.5  # spread 1.5x avg = uncertainty

MODIFIERS = {
    "strong_bull_long":  +6,
    "weak_bull_long":    +3,
    "strong_bear_short": +6,
    "weak_bear_short":   +3,
    "against_strong":    -5,
    "against_weak":      -3,
    "neutral":            0,
    "spread_wide":       -2,
    "spread_narrow":     +1,
}


@dataclass
class OrderFlowResult:
    ofi_score:        float = 0.5     # 0.0 (pure sell) to 1.0 (pure buy)
    ofi_signal:       str   = "NEUTRAL"  # STRONG_BUY/BUY/NEUTRAL/SELL/STRONG_SELL
    buy_pressure:     float = 0.0     # % of volume on bid-lifting (buy side)
    sell_pressure:    float = 0.0     # % of volume on ask-hitting (sell side)
    cumulative_delta: float = 0.0     # running buy-sell volume delta
    spread_bps:       Optional[float] = None   # current bid-ask spread in bps
    spread_signal:    str   = "UNKNOWN"  # NARROW / NORMAL / WIDE
    data_source:      str   = "bars_proxy"  # "quotes" or "bars_proxy"
    score_modifier:   int   = 0
    note:             str   = ""

    def get_journal_dict(self) -> dict:
        return {
            "ofi_score":     round(self.ofi_score, 3),
            "ofi_signal":    self.ofi_signal,
            "ofi_buy_pct":   round(self.buy_pressure, 3),
            "ofi_sell_pct":  round(self.sell_pressure, 3),
            "ofi_delta":     round(self.cumulative_delta, 0),
            "ofi_spread_bps":round(self.spread_bps, 1) if self.spread_bps else None,
            "ofi_spread_sig":self.spread_signal,
            "ofi_mod":       self.score_modifier,
        }

    def get_dashboard_dict(self) -> dict:
        return {
            "score":       round(self.ofi_score * 100, 1),
            "signal":      self.ofi_signal,
            "buy_pct":     round(self.buy_pressure * 100, 1),
            "sell_pct":    round(self.sell_pressure * 100, 1),
            "delta":       round(self.cumulative_delta, 0),
            "spread_bps":  round(self.spread_bps, 1) if self.spread_bps else None,
            "spread_sig":  self.spread_signal,
            "source":      self.data_source,
            "mod":         self.score_modifier,
            "note":        self.note,
        }

    def __str__(self):
        return (f"OFI: {self.ofi_signal} | score={self.ofi_score:.2f} "
                f"buy={self.buy_pressure*100:.0f}% sell={self.sell_pressure*100:.0f}% "
                f"delta={self.cumulative_delta:+.0f} | "
                f"spread={self.spread_signal} | mod={self.score_modifier:+d}")


class OrderFlowEngine:
    """
    Order flow imbalance detection for PMO Bot.

    Two modes:
    1. Quote mode: uses real-time bid/ask quote stream (more accurate)
    2. Bars proxy mode: approximates OFI from bar OHLCV (free tier fallback)

    For bars proxy:
    - If close > midpoint (H+L)/2 → more buying pressure that bar
    - Weight by volume
    - Cumulative delta = sum of (close_position * volume) across bars

    engine = OrderFlowEngine()

    # Bars proxy mode (always available):
    result = engine.analyze_bars(bars, trade_direction="long")

    # Quote mode (requires Alpaca quote data):
    result = engine.analyze_quotes(quotes, trade_direction="long")
    """

    def _bar_ofi(self, bar: dict) -> tuple:
        """
        Compute order flow imbalance for a single bar.
        Returns (buy_volume_proxy, sell_volume_proxy, delta)
        """
        o = float(bar.get("open",  0))
        h = float(bar.get("high",  0))
        l = float(bar.get("low",   0))
        c = float(bar.get("close", 0))
        v = float(bar.get("volume",0))

        if h <= l or v <= 0:
            return 0, 0, 0

        # Position of close within bar range (0=low, 1=high)
        bar_range = h - l
        close_pos = (c - l) / bar_range  # 0.0 to 1.0

        # Buy volume proxy: close in upper half = more buying
        buy_vol  = v * close_pos
        sell_vol = v * (1 - close_pos)
        delta    = buy_vol - sell_vol

        return buy_vol, sell_vol, delta

    def analyze_bars(self, bars: list,
                     trade_direction: str = "long",
                     lookback: int = 20) -> OrderFlowResult:
        """
        Compute OFI from bar data (proxy mode).
        bars: 5m bars oldest→newest
        """
        if not bars:
            return OrderFlowResult(note="no bars provided")

        recent = bars[-lookback:] if len(bars) > lookback else bars

        total_buy  = 0.0
        total_sell = 0.0
        cum_delta  = 0.0

        bar_ofis = []
        for bar in recent:
            bv, sv, delta = self._bar_ofi(bar)
            total_buy  += bv
            total_sell += sv
            cum_delta  += delta
            bar_ofis.append(delta)

        total_vol = total_buy + total_sell
        if total_vol <= 0:
            return OrderFlowResult(note="zero volume in bars")

        buy_pct  = total_buy  / total_vol
        sell_pct = total_sell / total_vol
        ofi      = buy_pct    # 0.5 = balanced, >0.5 = buy pressure

        # Determine signal
        if ofi >= OFI_STRONG_BULL:
            signal = "STRONG_BUY"
        elif ofi >= OFI_WEAK_BULL:
            signal = "BUY"
        elif ofi <= OFI_STRONG_BEAR:
            signal = "STRONG_SELL"
        elif ofi <= OFI_WEAK_BEAR:
            signal = "SELL"
        else:
            signal = "NEUTRAL"

        # Spread proxy: use bar range / midpoint as spread approximation
        spread_bps = None
        spread_sig = "UNKNOWN"
        if recent:
            ranges = []
            for bar in recent:
                h = float(bar.get("high",0))
                l = float(bar.get("low",0))
                mid = (h+l)/2
                if mid > 0: ranges.append((h-l)/mid*10000)
            if ranges:
                avg_range_bps = sum(ranges) / len(ranges)
                curr_range_bps = ranges[-1]
                spread_bps = round(curr_range_bps, 1)
                ratio = curr_range_bps / avg_range_bps if avg_range_bps > 0 else 1
                if ratio >= SPREAD_WIDENING_THRESHOLD:
                    spread_sig = "WIDE"
                elif ratio <= 0.7:
                    spread_sig = "NARROW"
                else:
                    spread_sig = "NORMAL"

        # Score modifier
        td = trade_direction.lower()
        mod = 0
        if signal == "STRONG_BUY":
            mod = MODIFIERS["strong_bull_long"] if td=="long" else MODIFIERS["against_strong"]
        elif signal == "BUY":
            mod = MODIFIERS["weak_bull_long"] if td=="long" else MODIFIERS["against_weak"]
        elif signal == "STRONG_SELL":
            mod = MODIFIERS["strong_bear_short"] if td=="short" else MODIFIERS["against_strong"]
        elif signal == "SELL":
            mod = MODIFIERS["weak_bear_short"] if td=="short" else MODIFIERS["against_weak"]

        if spread_sig == "WIDE":
            mod += MODIFIERS["spread_wide"]
        elif spread_sig == "NARROW":
            mod += MODIFIERS["spread_narrow"]

        mod = max(-10, min(10, mod))

        # Trend in recent bars (momentum)
        if len(bar_ofis) >= 5:
            recent5 = bar_ofis[-5:]
            if all(d > 0 for d in recent5):
                note = "consistent buy pressure last 5 bars"
            elif all(d < 0 for d in recent5):
                note = "consistent sell pressure last 5 bars"
            else:
                note = f"mixed pressure | last bar {'buy' if bar_ofis[-1]>0 else 'sell'}"
        else:
            note = "proxy mode (bars-based OFI)"

        return OrderFlowResult(
            ofi_score        = round(ofi, 4),
            ofi_signal       = signal,
            buy_pressure     = round(buy_pct, 4),
            sell_pressure    = round(sell_pct, 4),
            cumulative_delta = round(cum_delta, 0),
            spread_bps       = spread_bps,
            spread_signal    = spread_sig,
            data_source      = "bars_proxy",
            score_modifier   = mod,
            note             = note,
        )

    def analyze_quotes(self, quotes: list,
                       trade_direction: str = "long") -> OrderFlowResult:
        """
        Compute OFI from real Alpaca quote ticks.
        quotes: list of dicts with 'bp' (bid price), 'ap' (ask price),
                'bs' (bid size), 'as' (ask size), optionally 'c' (condition)
        """
        if not quotes:
            return OrderFlowResult(note="no quotes provided", data_source="quotes")

        buy_vol  = 0.0
        sell_vol = 0.0
        spreads  = []

        prev_mid = None
        for q in quotes:
            bp = float(q.get("bp", 0) or q.get("bid_price", 0))
            ap = float(q.get("ap", 0) or q.get("ask_price", 0))
            bs = float(q.get("bs", 0) or q.get("bid_size",  0))
            asz= float(q.get("as", 0) or q.get("ask_size",  0))

            if ap <= 0 or bp <= 0 or ap <= bp:
                continue

            mid = (bp + ap) / 2
            spread = (ap - bp) / mid * 10000  # in bps
            spreads.append(spread)

            # OFI: when ask decreases or bid increases = aggressive buying
            if prev_mid is not None:
                if mid > prev_mid:
                    buy_vol  += (bs + asz) / 2
                elif mid < prev_mid:
                    sell_vol += (bs + asz) / 2
            prev_mid = mid

        total = buy_vol + sell_vol
        if total <= 0:
            return OrderFlowResult(note="insufficient quote movement",
                                   data_source="quotes")

        ofi      = buy_vol / total
        buy_pct  = ofi
        sell_pct = 1 - ofi

        avg_spread = sum(spreads) / len(spreads) if spreads else 0
        curr_spread= spreads[-1] if spreads else 0
        spread_sig = ("WIDE" if curr_spread > avg_spread * 1.5
                      else "NARROW" if curr_spread < avg_spread * 0.7
                      else "NORMAL")

        if ofi >= OFI_STRONG_BULL:   signal = "STRONG_BUY"
        elif ofi >= OFI_WEAK_BULL:   signal = "BUY"
        elif ofi <= OFI_STRONG_BEAR: signal = "STRONG_SELL"
        elif ofi <= OFI_WEAK_BEAR:   signal = "SELL"
        else:                         signal = "NEUTRAL"

        td = trade_direction.lower()
        mod = 0
        if signal == "STRONG_BUY":
            mod = MODIFIERS["strong_bull_long"] if td=="long" else MODIFIERS["against_strong"]
        elif signal == "BUY":
            mod = MODIFIERS["weak_bull_long"] if td=="long" else MODIFIERS["against_weak"]
        elif signal == "STRONG_SELL":
            mod = MODIFIERS["strong_bear_short"] if td=="short" else MODIFIERS["against_strong"]
        elif signal == "SELL":
            mod = MODIFIERS["weak_bear_short"] if td=="short" else MODIFIERS["against_weak"]
        if spread_sig == "WIDE":   mod += MODIFIERS["spread_wide"]
        elif spread_sig == "NARROW": mod += MODIFIERS["spread_narrow"]
        mod = max(-10, min(10, mod))

        return OrderFlowResult(
            ofi_score        = round(ofi, 4),
            ofi_signal       = signal,
            buy_pressure     = round(buy_pct, 4),
            sell_pressure    = round(sell_pct, 4),
            cumulative_delta = round(buy_vol - sell_vol, 0),
            spread_bps       = round(curr_spread, 1),
            spread_signal    = spread_sig,
            data_source      = "quotes",
            score_modifier   = mod,
            note             = f"{len(quotes)} quotes analyzed",
        )


if __name__ == "__main__":
    import random, datetime
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("PMO Order Flow Engine — smoke test\n")
    random.seed(42)

    def make_trending_bars(n=20, bullish=True):
        bars, price = [], 100.0
        t = datetime.datetime(2026,6,16,9,30)
        for i in range(n):
            o = price
            move = random.uniform(0.1, 0.4) * (1 if bullish else -1)
            c = price + move + random.gauss(0, 0.1)
            if bullish:
                h = max(o,c) + random.uniform(0.05, 0.15)
                l = min(o,c) - random.uniform(0, 0.05)
            else:
                h = max(o,c) + random.uniform(0, 0.05)
                l = min(o,c) - random.uniform(0.05, 0.15)
            bars.append({"open":round(o,2),"high":round(h,2),"low":round(l,2),
                         "close":round(c,2),"volume":random.randint(50000,200000),
                         "datetime":t})
            price = c
            t += datetime.timedelta(minutes=5)
        return bars

    engine = OrderFlowEngine()

    print("=== Strong uptrend (should be STRONG_BUY, long=+6) ===")
    r = engine.analyze_bars(make_trending_bars(20, bullish=True), "long")
    print(f"  {r}")

    print()
    print("=== Strong downtrend (long=against = -5) ===")
    r2 = engine.analyze_bars(make_trending_bars(20, bullish=False), "long")
    print(f"  {r2}")

    print()
    print("=== Strong downtrend (short=aligned = +6) ===")
    r3 = engine.analyze_bars(make_trending_bars(20, bullish=False), "short")
    print(f"  {r3}")

    print()
    print("Journal dict:", r.get_journal_dict())
    print("\nSmoke test complete.")
