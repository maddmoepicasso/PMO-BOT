"""
PMO Sentiment Engine — pmo_sentiment_engine.py
===============================================
Read-only market sentiment signals for PMO Bot.
Logs to journal and dashboard. Does NOT affect score until validated.

Sources (all free, no API key required):
  1. CNN Fear & Greed Index  — alternative.me/fng
  2. VIX level               — Yahoo Finance ^VIX
  3. SPY 20-day trend        — Yahoo Finance SPY
  4. Put/Call ratio          — Yahoo Finance ^PCCE (CBOE equity P/C)

Sentiment output:
  sentiment_score    : -100 (extreme fear) to +100 (extreme greed)
  sentiment_label    : EXTREME_FEAR / FEAR / NEUTRAL / GREED / EXTREME_GREED
  vix_level          : float
  vix_regime         : LOW / NORMAL / ELEVATED / EXTREME
  market_trend       : BULLISH / NEUTRAL / BEARISH (SPY 20d)
  put_call_ratio     : float
  pc_signal          : BULLISH / NEUTRAL / BEARISH (contrarian)
  composite_signal   : BULLISH / NEUTRAL / BEARISH

Usage:
    from pmo_sentiment_engine import SentimentEngine
    engine = SentimentEngine()
    result = engine.read()
    print(result)
    print(result.get_journal_dict())
"""

import logging
import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta

logger = logging.getLogger("pmo.sentiment_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIX_THRESHOLDS = {
    "LOW":      (0,   15),
    "NORMAL":   (15,  20),
    "ELEVATED": (20,  30),
    "EXTREME":  (30, 999),
}

FNG_LABELS = {
    (0,  25): "EXTREME_FEAR",
    (25, 45): "FEAR",
    (45, 55): "NEUTRAL",
    (55, 75): "GREED",
    (75,101): "EXTREME_GREED",
}

# Put/call ratio thresholds (equity P/C, contrarian)
# High P/C = lots of puts = fear = contrarian bullish
PC_BULLISH_THRESHOLD  = 0.85   # P/C > 0.85 → contrarian bullish
PC_BEARISH_THRESHOLD  = 0.55   # P/C < 0.55 → contrarian bearish

# Cache TTL — sentiment data doesn't need to refresh every cycle
CACHE_TTL_SECONDS = 300   # 5 minutes

# Yahoo Finance base URL
YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

@dataclass
class SentimentResult:
    """Full sentiment snapshot."""
    # Fear & Greed
    fng_value:          Optional[int]   = None   # 0-100
    fng_label:          str             = "UNKNOWN"
    fng_classification: str             = "UNKNOWN"  # CNN's own label

    # VIX
    vix_level:          Optional[float] = None
    vix_regime:         str             = "UNKNOWN"
    vix_signal:         str             = "NEUTRAL"  # LOW→BULLISH, EXTREME→BEARISH

    # Market trend (SPY)
    spy_price:          Optional[float] = None
    spy_sma20:          Optional[float] = None
    market_trend:       str             = "NEUTRAL"  # BULLISH / NEUTRAL / BEARISH

    # Put/Call
    put_call_ratio:     Optional[float] = None
    pc_signal:          str             = "NEUTRAL"

    # Composite
    sentiment_score:    int             = 0      # -100 to +100
    composite_signal:   str             = "NEUTRAL"

    # Meta
    timestamp:          Optional[str]   = None
    sources_available:  int             = 0
    error:              Optional[str]   = None

    def get_journal_dict(self) -> dict:
        return {
            "sentiment_fng":        self.fng_value,
            "sentiment_fng_label":  self.fng_label,
            "sentiment_vix":        round(self.vix_level, 2) if self.vix_level else None,
            "sentiment_vix_regime": self.vix_regime,
            "sentiment_market_trend": self.market_trend,
            "sentiment_pc_ratio":   round(self.put_call_ratio, 3) if self.put_call_ratio else None,
            "sentiment_score":      self.sentiment_score,
            "sentiment_signal":     self.composite_signal,
        }

    def get_dashboard_dict(self) -> dict:
        """Compact dict for /api/deck/snapshot."""
        return {
            "score":    self.sentiment_score,
            "signal":   self.composite_signal,
            "fng":      self.fng_value,
            "fng_label": self.fng_label,
            "vix":      round(self.vix_level, 1) if self.vix_level else None,
            "vix_regime": self.vix_regime,
            "trend":    self.market_trend,
            "pc_ratio": round(self.put_call_ratio, 2) if self.put_call_ratio else None,
            "pc_signal": self.pc_signal,
            "timestamp": self.timestamp,
            "sources":  self.sources_available,
        }

    def __str__(self):
        parts = [f"Sentiment: {self.composite_signal} (score={self.sentiment_score:+d})"]
        if self.fng_value is not None:
            parts.append(f"F&G={self.fng_value}({self.fng_label})")
        if self.vix_level is not None:
            parts.append(f"VIX={self.vix_level:.1f}({self.vix_regime})")
        if self.market_trend != "NEUTRAL":
            parts.append(f"SPY={self.market_trend}")
        if self.put_call_ratio is not None:
            parts.append(f"P/C={self.put_call_ratio:.2f}({self.pc_signal})")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def _fetch_url(url: str, timeout: int = 6) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers=YF_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        logger.debug("Fetch error %s: %s", url, e)
        return None


def _fetch_fng() -> tuple:
    """Returns (fng_value: int, fng_classification: str) or (None, 'UNKNOWN')."""
    data = _fetch_url("https://api.alternative.me/fng/?limit=1&format=json", timeout=5)
    if not data:
        return None, "UNKNOWN"
    try:
        entry = data["data"][0]
        val   = int(entry["value"])
        label = entry.get("value_classification", "UNKNOWN").upper().replace(" ", "_")
        return val, label
    except Exception as e:
        logger.debug("F&G parse error: %s", e)
        return None, "UNKNOWN"


def _fetch_yf_closes(symbol: str, days: int = 25) -> list:
    """Returns list of closing prices for symbol, oldest first."""
    url = f"{YF_BASE}/{symbol}?interval=1d&range={days}d"
    data = _fetch_url(url)
    if not data:
        return []
    try:
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        return [c for c in closes if c is not None]
    except Exception as e:
        logger.debug("YF parse error %s: %s", symbol, e)
        return []


def _vix_regime(vix: float) -> tuple:
    """Returns (regime, signal)."""
    for regime, (lo, hi) in VIX_THRESHOLDS.items():
        if lo <= vix < hi:
            if regime == "LOW":
                return regime, "BULLISH"
            elif regime == "NORMAL":
                return regime, "NEUTRAL"
            elif regime == "ELEVATED":
                return regime, "BEARISH"
            else:
                return regime, "BEARISH"
    return "EXTREME", "BEARISH"


def _fng_label(val: int) -> str:
    for (lo, hi), label in FNG_LABELS.items():
        if lo <= val < hi:
            return label
    return "UNKNOWN"


def _pc_signal(ratio: float) -> str:
    if ratio >= PC_BULLISH_THRESHOLD:
        return "BULLISH"   # contrarian — lots of puts = fear = bounce coming
    elif ratio <= PC_BEARISH_THRESHOLD:
        return "BEARISH"   # contrarian — too many calls = complacency
    return "NEUTRAL"


def _composite_score(fng_val, vix_sig, trend, pc_sig) -> int:
    """
    Build a -100 to +100 composite score from available signals.
    Each signal contributes a weighted vote.
    """
    score = 0
    weight_total = 0

    # F&G: most reliable single sentiment indicator (weight 40)
    if fng_val is not None:
        # Map 0-100 to -50..+50 then scale to weight
        fng_centered = (fng_val - 50) / 50 * 40
        score += fng_centered
        weight_total += 40

    # VIX signal (weight 30)
    vix_map = {"BULLISH": +30, "NEUTRAL": 0, "BEARISH": -30}
    if vix_sig in vix_map:
        score += vix_map[vix_sig]
        weight_total += 30

    # Market trend (weight 20)
    trend_map = {"BULLISH": +20, "NEUTRAL": 0, "BEARISH": -20}
    if trend in trend_map:
        score += trend_map[trend]
        weight_total += 20

    # Put/Call contrarian (weight 10)
    pc_map = {"BULLISH": +10, "NEUTRAL": 0, "BEARISH": -10}
    if pc_sig in pc_map:
        score += pc_map[pc_sig]
        weight_total += 10

    if weight_total == 0:
        return 0

    # Normalize to -100..+100
    normalized = int(score / weight_total * 100)
    return max(-100, min(100, normalized))


def _signal_from_score(score: int) -> str:
    if score >= 20:
        return "BULLISH"
    elif score <= -20:
        return "BEARISH"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class SentimentEngine:
    """
    Fetches and caches market sentiment from free public sources.

    engine = SentimentEngine()
    result = engine.read()           # fetches fresh or returns cached
    result = engine.read(force=True) # always fetch fresh
    """

    def __init__(self, cache_ttl: int = CACHE_TTL_SECONDS):
        self._cache: Optional[SentimentResult] = None
        self._cache_time: Optional[float] = None
        self._ttl = cache_ttl

    def _is_cache_valid(self) -> bool:
        if self._cache is None or self._cache_time is None:
            return False
        return (time.time() - self._cache_time) < self._ttl

    def read(self, force: bool = False) -> SentimentResult:
        """
        Returns a SentimentResult. Uses cache if fresh (< 5 min old).
        Set force=True to bypass cache.
        """
        if not force and self._is_cache_valid():
            logger.debug("SentimentEngine: returning cached result")
            return self._cache

        result = SentimentResult(timestamp=datetime.now(tz=__import__('datetime').timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        sources = 0

        # 1. Fear & Greed
        fng_val, fng_class = _fetch_fng()
        if fng_val is not None:
            result.fng_value          = fng_val
            result.fng_label          = _fng_label(fng_val)
            result.fng_classification = fng_class
            sources += 1
            logger.info("SentimentEngine: F&G=%d (%s)", fng_val, result.fng_label)

        # 2. VIX
        vix_closes = _fetch_yf_closes("%5EVIX", days=5)
        if vix_closes:
            vix = vix_closes[-1]
            result.vix_level  = round(vix, 2)
            result.vix_regime, result.vix_signal = _vix_regime(vix)
            sources += 1
            logger.info("SentimentEngine: VIX=%.2f (%s)", vix, result.vix_regime)

        # 3. SPY 20-day trend
        spy_closes = _fetch_yf_closes("SPY", days=25)
        if len(spy_closes) >= 20:
            sma20 = sum(spy_closes[-20:]) / 20
            spy   = spy_closes[-1]
            result.spy_price = round(spy, 2)
            result.spy_sma20 = round(sma20, 2)
            pct_above = (spy - sma20) / sma20 * 100
            if pct_above > 1.0:
                result.market_trend = "BULLISH"
            elif pct_above < -1.0:
                result.market_trend = "BEARISH"
            else:
                result.market_trend = "NEUTRAL"
            sources += 1
            logger.info("SentimentEngine: SPY=%.2f SMA20=%.2f trend=%s",
                        spy, sma20, result.market_trend)

        # 4. Put/Call ratio (CBOE equity P/C)
        pc_closes = _fetch_yf_closes("%5EPCCE", days=3)
        if pc_closes:
            ratio = pc_closes[-1]
            result.put_call_ratio = round(ratio, 3)
            result.pc_signal      = _pc_signal(ratio)
            sources += 1
            logger.info("SentimentEngine: P/C=%.3f signal=%s", ratio, result.pc_signal)

        # Composite
        result.sentiment_score  = _composite_score(
            result.fng_value, result.vix_signal,
            result.market_trend, result.pc_signal
        )
        result.composite_signal = _signal_from_score(result.sentiment_score)
        result.sources_available = sources

        if sources == 0:
            result.error = "No sentiment sources available (network or market closed)"
            logger.warning("SentimentEngine: all sources failed")

        self._cache      = result
        self._cache_time = time.time()
        return result

    def get_dashboard_dict(self) -> dict:
        """Convenience — read() + get_dashboard_dict() in one call."""
        return self.read().get_dashboard_dict()


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("PMO Sentiment Engine — smoke test\n")

    engine = SentimentEngine()

    # Test with mock data (simulating what real fetch returns)
    from unittest.mock import patch

    mock_fng = (72, "GREED")
    mock_vix = [18.5, 19.1, 18.8]
    mock_spy = [460 + i*0.3 for i in range(22)]
    mock_pc  = [0.72]

    with patch("pmo_sentiment_engine._fetch_fng", return_value=mock_fng), \
         patch("pmo_sentiment_engine._fetch_yf_closes", side_effect=[mock_vix, mock_spy, mock_pc]):
        result = engine.read(force=True)

    print(f"Result:      {result}")
    print(f"Journal:     {result.get_journal_dict()}")
    print(f"Dashboard:   {result.get_dashboard_dict()}")
    print()

    # Test cache
    result2 = engine.read()
    print(f"Cache hit:   {result2 is result}")
    print("\nSmoke test complete.")