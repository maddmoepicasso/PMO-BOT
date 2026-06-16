"""
PMO Pullback Signal

Clean signal function for forward paper testing after robustness passes.
This module does not submit orders. It only evaluates daily OHLCV bars and
returns a trade decision dictionary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

import pandas as pd


@dataclass
class PullbackSignalConfig:
    reward_risk: float = 1.5
    sma_fast: int = 20
    sma_slow: int = 50
    market_sma: int = 200
    slope_lookback: int = 5
    pullback_tolerance_pct: float = 1.25
    max_extension_pct: float = 5.0
    max_recent_gain_pct: float = 8.0
    recent_gain_lookback: int = 5
    atr_period: int = 14
    atr_multiple: float = 1.5
    stop_lookback: int = 5
    stop_buffer_pct: float = 0.25
    stop_mode: str = "wider"
    min_price: float = 2.0


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def normalize_daily_bars(frame: pd.DataFrame) -> pd.DataFrame:
    df = frame.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(col[0]).strip() if isinstance(col, tuple) else str(col).strip() for col in df.columns]
    rename = {}
    for col in df.columns:
        clean = str(col).strip().lower()
        if clean in {"date", "timestamp", "time", "datetime", "t"}:
            rename[col] = "date"
        elif clean in {"open", "o"}:
            rename[col] = "open"
        elif clean in {"high", "h"}:
            rename[col] = "high"
        elif clean in {"low", "l"}:
            rename[col] = "low"
        elif clean in {"close", "c"}:
            rename[col] = "close"
        elif clean in {"volume", "v"}:
            rename[col] = "volume"
    df = df.rename(columns=rename)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).set_index("date")
    else:
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df[~df.index.isna()]
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).sort_index()


def add_signal_indicators(frame: pd.DataFrame, config: PullbackSignalConfig) -> pd.DataFrame:
    df = normalize_daily_bars(frame)
    df["sma_fast"] = df["close"].rolling(config.sma_fast).mean()
    df["sma_slow"] = df["close"].rolling(config.sma_slow).mean()
    df["fast_slope"] = df["sma_fast"] - df["sma_fast"].shift(config.slope_lookback)
    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = true_range.rolling(config.atr_period).mean()
    df["extension_pct"] = ((df["close"] - df["sma_fast"]) / df["sma_fast"]) * 100
    df["recent_gain_pct"] = ((df["close"] / df["close"].shift(config.recent_gain_lookback)) - 1) * 100
    df["near_fast_ma"] = df["low"] <= df["sma_fast"] * (1 + config.pullback_tolerance_pct / 100)
    df["bullish_bounce"] = (df["close"] > df["sma_fast"]) & (df["close"] > df["open"])
    df["uptrend"] = (df["close"] > df["sma_slow"]) & (df["sma_fast"] > df["sma_slow"]) & (df["fast_slope"] > 0)
    return df


def market_regime_ok(market_bars: pd.DataFrame, config: PullbackSignalConfig) -> Dict[str, Any]:
    market = normalize_daily_bars(market_bars)
    if len(market) < config.market_sma:
        return {"ok": False, "reason": f"market needs {config.market_sma}+ bars"}
    market["market_sma"] = market["close"].rolling(config.market_sma).mean()
    latest = market.dropna().iloc[-1]
    close = safe_float(latest["close"])
    sma = safe_float(latest["market_sma"])
    return {
        "ok": close > sma,
        "close": round(close, 4),
        "market_sma": round(sma, 4),
        "reason": "market above 200SMA" if close > sma else "market below 200SMA",
    }


def pmo_pullback_signal(
    symbol: str,
    symbol_bars: pd.DataFrame,
    market_bars: pd.DataFrame,
    config: Optional[PullbackSignalConfig] = None,
) -> Dict[str, Any]:
    config = config or PullbackSignalConfig()
    market = market_regime_ok(market_bars, config)
    if not market["ok"]:
        return {"ok": True, "decision": "NO_TRADE", "symbol": symbol, "reason": market["reason"], "market": market}

    bars = add_signal_indicators(symbol_bars, config).dropna()
    if len(bars) < max(config.sma_slow, config.atr_period, config.stop_lookback) + 5:
        return {"ok": True, "decision": "NO_TRADE", "symbol": symbol, "reason": "not enough symbol bars", "market": market}
    latest = bars.iloc[-1]
    blockers = []
    close = safe_float(latest["close"])
    if close < config.min_price:
        blockers.append("price below minimum")
    if not bool(latest["uptrend"]):
        blockers.append("symbol not in rising uptrend")
    if not bool(latest["near_fast_ma"]):
        blockers.append("not a pullback to fast SMA")
    if not bool(latest["bullish_bounce"]):
        blockers.append("no bullish bounce confirmation")
    if safe_float(latest["extension_pct"]) > config.max_extension_pct:
        blockers.append("too extended above fast SMA")
    if safe_float(latest["recent_gain_pct"]) > config.max_recent_gain_pct:
        blockers.append("recent move already ran too far")
    if blockers:
        return {
            "ok": True,
            "decision": "NO_TRADE",
            "symbol": symbol,
            "reason": " | ".join(blockers),
            "market": market,
            "metrics": {
                "close": round(close, 4),
                "sma_fast": round(safe_float(latest["sma_fast"]), 4),
                "sma_slow": round(safe_float(latest["sma_slow"]), 4),
                "extension_pct": round(safe_float(latest["extension_pct"]), 3),
                "recent_gain_pct": round(safe_float(latest["recent_gain_pct"]), 3),
            },
        }

    swing_low = safe_float(bars.iloc[-config.stop_lookback:]["low"].min())
    entry_price = close
    swing_stop = swing_low * (1 - config.stop_buffer_pct / 100)
    atr = safe_float(latest["atr"])
    atr_stop = entry_price - atr * config.atr_multiple
    if config.stop_mode == "atr":
        stop_price = atr_stop
    elif config.stop_mode == "tighter":
        stop_price = max(swing_stop, atr_stop)
    elif config.stop_mode == "wider":
        stop_price = min(swing_stop, atr_stop)
    else:
        stop_price = swing_stop
    risk = entry_price - stop_price
    if risk <= 0:
        return {"ok": True, "decision": "NO_TRADE", "symbol": symbol, "reason": "invalid stop risk", "market": market}
    target_price = entry_price + risk * config.reward_risk
    score = 80
    if safe_float(latest["fast_slope"]) > 0:
        score += 5
    if safe_float(latest["extension_pct"]) <= config.pullback_tolerance_pct:
        score += 5
    if market["ok"]:
        score += 5
    return {
        "ok": True,
        "decision": "BUY",
        "symbol": symbol.upper(),
        "side": "LONG",
        "score": min(score, 95),
        "entry_price": round(entry_price, 4),
        "stop_loss_price": round(stop_price, 4),
        "take_profit_price": round(target_price, 4),
        "risk_per_share": round(risk, 4),
        "reward_risk": config.reward_risk,
        "reason": "Validated pullback signal: market regime on, symbol uptrend, pullback bounce, not extended.",
        "market": market,
        "metrics": {
            "close": round(close, 4),
            "sma_fast": round(safe_float(latest["sma_fast"]), 4),
            "sma_slow": round(safe_float(latest["sma_slow"]), 4),
            "atr": round(atr, 4),
            "extension_pct": round(safe_float(latest["extension_pct"]), 3),
            "recent_gain_pct": round(safe_float(latest["recent_gain_pct"]), 3),
        },
        "config": asdict(config),
    }


if __name__ == "__main__":
    # Tiny smoke test on generated data; real use imports pmo_pullback_signal().
    dates = pd.bdate_range("2025-01-01", periods=260)
    close = pd.Series(range(260), index=dates).astype(float) * 0.2 + 100
    bars = pd.DataFrame({
        "date": dates,
        "open": close.values - 0.1,
        "high": close.values + 0.5,
        "low": close.values - 0.5,
        "close": close.values,
        "volume": 1000000,
    })
    print(pmo_pullback_signal("PMO_TEST", bars, bars))
