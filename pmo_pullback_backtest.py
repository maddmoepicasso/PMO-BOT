"""
PMO Pullback Backtest

Standalone strategy lab for testing a simple pullback-in-uptrend idea before
letting PMO BOT paper-trade it. This file does not import pmo_bot.py, does not
place orders, and does not touch broker APIs unless you explicitly use optional
yfinance data download.

Default strategy:
- Trade only symbols in an uptrend: close > 50 SMA and 20 SMA > 50 SMA.
- Arm a setup when price pulls back near the 20 SMA.
- Enter next session after a bounce confirmation.
- Stop under recent swing low.
- Target at risk/reward multiple, default 2R.
- Risk a fixed percent of capital per trade.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, replace
from itertools import product
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = ROOT / "pmo_csv" / "backtest_daily_bars"
DEFAULT_OUTPUT_DIR = ROOT / "pmo_reports" / "backtests"
DEFAULT_SYMBOLS = [
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMD",
    "META",
    "AMZN",
    "TSLA",
    "JPM",
    "XLF",
    "XLK",
    "XLY",
    "XLV",
]
UNIVERSE_PRESETS = {
    "default": DEFAULT_SYMBOLS,
    "pmo_best": ["SPY", "QQQ", "XLK", "MSFT"],
    "index_tech": ["SPY", "QQQ", "XLK", "AAPL", "MSFT", "META", "AMZN"],
    "mega_cap": ["AAPL", "MSFT", "NVDA", "META", "AMZN", "GOOGL", "TSLA"],
    "sector_etf": ["SPY", "QQQ", "XLK", "XLY", "XLF", "XLV"],
}


@dataclass
class BacktestConfig:
    initial_capital: float = 10_000.0
    risk_per_trade_pct: float = 1.0
    reward_risk: float = 2.0
    sma_fast: int = 20
    sma_slow: int = 50
    slope_lookback: int = 5
    pullback_tolerance_pct: float = 1.25
    stop_lookback: int = 5
    stop_buffer_pct: float = 0.25
    max_hold_days: int = 15
    min_price: float = 2.0
    market_filter_symbol: str = "SPY"
    market_filter_confirm_symbol: str = "QQQ"
    market_filter_mode: str = "spy_above_sma"
    market_filter_sma: int = 200
    market_filter_fast_sma: int = 50
    market_slope_lookback: int = 20
    market_drawdown_lookback: int = 63
    market_max_drawdown_pct: float = 10.0
    require_market_uptrend: bool = False
    max_extension_pct: float = 3.0
    max_recent_gain_pct: float = 8.0
    recent_gain_lookback: int = 5
    atr_period: int = 14
    atr_multiple: float = 1.5
    stop_mode: str = "swing"
    universe_name: str = "custom"


@dataclass
class Trade:
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    qty: float
    stop_price: float
    target_price: float
    risk_per_share: float
    pnl_usd: float
    pnl_pct: float
    r_multiple: float
    outcome: str
    hold_days: int
    entry_reason: str
    exit_reason: str


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [str(col[0]).strip() if isinstance(col, tuple) else str(col).strip() for col in df.columns]
    rename_map = {}
    for col in df.columns:
        clean = str(col).strip().lower()
        if clean in {"date", "timestamp", "time", "datetime"}:
            rename_map[col] = "date"
        elif clean in {"open", "o"}:
            rename_map[col] = "open"
        elif clean in {"high", "h"}:
            rename_map[col] = "high"
        elif clean in {"low", "l"}:
            rename_map[col] = "low"
        elif clean in {"close", "c"}:
            rename_map[col] = "close"
        elif clean in {"adj close", "adj_close"}:
            rename_map[col] = "adj_close"
        elif clean in {"volume", "v"}:
            rename_map[col] = "volume"
    df = df.rename(columns=rename_map)
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {sorted(missing)}")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).sort_values("date")
        df = df.set_index("date")
    else:
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df[~df.index.isna()].sort_index()
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[["open", "high", "low", "close"] + (["volume"] if "volume" in df.columns else [])]


def load_csv_data(data_dir: Path, symbols: Iterable[str]) -> Dict[str, pd.DataFrame]:
    data: Dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        candidates = [
            data_dir / f"{symbol}.csv",
            data_dir / f"{symbol.replace('/', '_')}.csv",
            data_dir / f"{symbol.replace('/', '-')}.csv",
        ]
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if not path:
            continue
        try:
            data[symbol] = normalize_ohlcv(pd.read_csv(path))
        except Exception as exc:
            print(f"SKIP {symbol}: {path.name} could not load: {exc}")
    return data


def load_yfinance_data(symbols: Iterable[str], period: str) -> Dict[str, pd.DataFrame]:
    try:
        import yfinance as yf
    except Exception as exc:
        raise RuntimeError("yfinance is not installed. Run: pip install yfinance") from exc
    data: Dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        raw = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False)
        if raw is None or raw.empty:
            print(f"SKIP {symbol}: no yfinance data")
            continue
        raw = raw.reset_index()
        data[symbol] = normalize_ohlcv(raw)
    return data


def synthetic_data() -> Dict[str, pd.DataFrame]:
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2024-01-02", periods=320)
    series: Dict[str, pd.DataFrame] = {}
    for symbol, drift, noise in [("PMO_UP", 0.0012, 0.018), ("PMO_CHOP", 0.0001, 0.022), ("PMO_WEAK", -0.0004, 0.02)]:
        close = [100.0]
        for _ in range(1, len(dates)):
            close.append(close[-1] * (1 + drift + rng.normal(0, noise)))
        close_arr = np.array(close)
        open_arr = close_arr * (1 + rng.normal(0, 0.004, len(close_arr)))
        high_arr = np.maximum(open_arr, close_arr) * (1 + rng.uniform(0.002, 0.016, len(close_arr)))
        low_arr = np.minimum(open_arr, close_arr) * (1 - rng.uniform(0.002, 0.016, len(close_arr)))
        volume = rng.integers(500_000, 5_000_000, len(close_arr))
        series[symbol] = pd.DataFrame(
            {"open": open_arr, "high": high_arr, "low": low_arr, "close": close_arr, "volume": volume},
            index=dates,
        )
    return series


def add_indicators(df: pd.DataFrame, config: BacktestConfig) -> pd.DataFrame:
    out = df.copy()
    out["sma_fast"] = out["close"].rolling(config.sma_fast).mean()
    out["sma_slow"] = out["close"].rolling(config.sma_slow).mean()
    out["fast_slope"] = out["sma_fast"] - out["sma_fast"].shift(config.slope_lookback)
    prev_close = out["close"].shift(1)
    true_range = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = true_range.rolling(config.atr_period).mean()
    out["near_fast_ma"] = out["low"] <= out["sma_fast"] * (1 + config.pullback_tolerance_pct / 100)
    out["bullish_bounce"] = (out["close"] > out["sma_fast"]) & (out["close"] > out["open"])
    out["uptrend"] = (out["close"] > out["sma_slow"]) & (out["sma_fast"] > out["sma_slow"]) & (out["fast_slope"] > 0)
    out["extension_pct"] = ((out["close"] - out["sma_fast"]) / out["sma_fast"]) * 100
    out["recent_gain_pct"] = ((out["close"] / out["close"].shift(config.recent_gain_lookback)) - 1) * 100
    out["not_extended"] = out["extension_pct"] <= config.max_extension_pct
    out["not_chasing"] = out["recent_gain_pct"] <= config.max_recent_gain_pct
    out["entry_signal"] = out["uptrend"] & out["near_fast_ma"] & out["bullish_bounce"] & out["not_extended"] & out["not_chasing"]
    return out


def run_symbol_backtest(
    symbol: str,
    df: pd.DataFrame,
    config: BacktestConfig,
    market_filter: Optional[pd.Series] = None,
) -> List[Trade]:
    data = add_indicators(df, config).dropna().copy()
    if market_filter is not None:
        aligned_filter = market_filter.reindex(data.index).ffill().fillna(False)
        data["market_ok"] = aligned_filter.astype(bool)
    else:
        data["market_ok"] = True
    trades: List[Trade] = []
    if len(data) < config.sma_slow + config.stop_lookback + 5:
        return trades

    in_trade = False
    entry_idx = -1
    entry_price = 0.0
    stop_price = 0.0
    target_price = 0.0
    qty = 0.0
    capital = config.initial_capital

    for i in range(config.stop_lookback + 1, len(data) - 1):
        today = data.iloc[i]
        next_day = data.iloc[i + 1]
        if not in_trade:
            if not bool(today["market_ok"]) or not bool(today["entry_signal"]) or safe_float(today["close"]) < config.min_price:
                continue
            swing_low = safe_float(data.iloc[i - config.stop_lookback : i + 1]["low"].min())
            entry_price = safe_float(next_day["open"])
            swing_stop = swing_low * (1 - config.stop_buffer_pct / 100)
            atr = safe_float(today.get("atr"), 0)
            atr_stop = entry_price - (atr * config.atr_multiple) if atr > 0 else swing_stop
            if config.stop_mode == "atr":
                stop_price = atr_stop
            elif config.stop_mode == "wider":
                stop_price = min(swing_stop, atr_stop)
            elif config.stop_mode == "tighter":
                stop_price = max(swing_stop, atr_stop)
            else:
                stop_price = swing_stop
            risk_per_share = entry_price - stop_price
            if entry_price <= 0 or stop_price <= 0 or risk_per_share <= 0:
                continue
            risk_budget = capital * (config.risk_per_trade_pct / 100)
            qty = risk_budget / risk_per_share
            if qty <= 0:
                continue
            target_price = entry_price + risk_per_share * config.reward_risk
            in_trade = True
            entry_idx = i + 1
            continue

        high = safe_float(today["high"])
        low = safe_float(today["low"])
        close = safe_float(today["close"])
        hold_days = i - entry_idx
        exit_price: Optional[float] = None
        exit_reason = ""

        # Conservative same-day ordering: if both target and stop are touched,
        # count the stop first. This avoids overstating edge.
        if low <= stop_price:
            exit_price = stop_price
            exit_reason = "STOP"
        elif high >= target_price:
            exit_price = target_price
            exit_reason = "TARGET"
        elif hold_days >= config.max_hold_days:
            exit_price = close
            exit_reason = "MAX_HOLD"

        if exit_price is None:
            continue

        pnl = (exit_price - entry_price) * qty
        capital += pnl
        risk_per_share = entry_price - stop_price
        r_multiple = (exit_price - entry_price) / risk_per_share if risk_per_share else 0.0
        trades.append(
            Trade(
                symbol=symbol,
                entry_date=str(data.index[entry_idx].date()),
                exit_date=str(data.index[i].date()),
                entry_price=round(entry_price, 4),
                exit_price=round(exit_price, 4),
                qty=round(qty, 6),
                stop_price=round(stop_price, 4),
                target_price=round(target_price, 4),
                risk_per_share=round(risk_per_share, 4),
                pnl_usd=round(pnl, 2),
                pnl_pct=round(((exit_price - entry_price) / entry_price) * 100, 3),
                r_multiple=round(r_multiple, 3),
                outcome="WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT",
                hold_days=hold_days,
                entry_reason=(
                    "Uptrend pullback to rising SMA with bullish bounce; "
                    f"market_filter={bool(today['market_ok'])}; "
                    f"extension={safe_float(today.get('extension_pct')):.2f}%; "
                    f"recent_gain={safe_float(today.get('recent_gain_pct')):.2f}%"
                ),
                exit_reason=exit_reason,
            )
        )
        in_trade = False

    return trades


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def summarize(trades: List[Trade], config: BacktestConfig) -> Dict[str, object]:
    trade_dicts = [asdict(trade) for trade in trades]
    wins = [trade for trade in trades if trade.pnl_usd > 0]
    losses = [trade for trade in trades if trade.pnl_usd < 0]
    gross_profit = sum(trade.pnl_usd for trade in wins)
    gross_loss = abs(sum(trade.pnl_usd for trade in losses))
    net_pnl = gross_profit - gross_loss
    trade_count = len(trades)
    win_rate = len(wins) / trade_count if trade_count else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss else (999.0 if gross_profit > 0 else 0.0)
    expectancy = net_pnl / trade_count if trade_count else 0.0
    avg_r = sum(trade.r_multiple for trade in trades) / trade_count if trade_count else 0.0
    equity = config.initial_capital
    peak = equity
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.pnl_usd
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    symbol_stats = []
    for symbol in sorted({trade.symbol for trade in trades}):
        group = [trade for trade in trades if trade.symbol == symbol]
        symbol_wins = [trade for trade in group if trade.pnl_usd > 0]
        symbol_loss = abs(sum(trade.pnl_usd for trade in group if trade.pnl_usd < 0))
        symbol_profit = sum(trade.pnl_usd for trade in symbol_wins)
        symbol_stats.append(
            {
                "symbol": symbol,
                "trades": len(group),
                "wins": len(symbol_wins),
                "losses": len([trade for trade in group if trade.pnl_usd < 0]),
                "win_rate": round(len(symbol_wins) / len(group), 3) if group else 0,
                "net_pnl": round(sum(trade.pnl_usd for trade in group), 2),
                "profit_factor": round(symbol_profit / symbol_loss, 3) if symbol_loss else (999.0 if symbol_profit > 0 else 0.0),
            }
        )
    verdict = "NO_EDGE"
    if trade_count < 50:
        verdict = "TOO_FEW_TRADES"
    elif profit_factor >= 1.5 and win_rate >= 0.42 and net_pnl > 0:
        verdict = "PROMISING_EDGE_NEEDS_FORWARD_TEST"
    elif profit_factor >= 1.2 and net_pnl > 0:
        verdict = "MARGINAL_EDGE_NEEDS_MORE_DATA"
    return {
        "verdict": verdict,
        "trade_count": trade_count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 3),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_pnl": round(net_pnl, 2),
        "return_pct": round((net_pnl / config.initial_capital) * 100, 2),
        "profit_factor": round(profit_factor, 3),
        "expectancy_usd": round(expectancy, 2),
        "average_r_multiple": round(avg_r, 3),
        "max_drawdown_usd": round(abs(max_drawdown), 2),
        "max_drawdown_pct": round((abs(max_drawdown) / config.initial_capital) * 100, 2),
        "config": asdict(config),
        "symbol_stats": sorted(symbol_stats, key=lambda row: row["net_pnl"], reverse=True),
        "sample_trades": trade_dicts[:10],
    }


def research_score(summary: Dict[str, object]) -> float:
    trades = safe_float(summary.get("trade_count"), 0)
    profit_factor = safe_float(summary.get("profit_factor"), 0)
    net_pnl = safe_float(summary.get("net_pnl"), 0)
    drawdown = safe_float(summary.get("max_drawdown_pct"), 999)
    win_rate = safe_float(summary.get("win_rate"), 0)
    if trades < 30 or net_pnl <= 0:
        return -999.0 + trades / 100
    return round((profit_factor * 100) + (win_rate * 25) + (net_pnl / 100) - (drawdown * 4), 3)


def save_outputs(trades: List[Trade], summary: Dict[str, object], output_dir: Path) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    trades_path = output_dir / "pmo_pullback_backtest_trades.csv"
    summary_path = output_dir / "pmo_pullback_backtest_summary.json"
    pd.DataFrame([asdict(trade) for trade in trades]).to_csv(trades_path, index=False)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return trades_path, summary_path


def market_filter_series(data: Dict[str, pd.DataFrame], config: BacktestConfig) -> Optional[pd.Series]:
    if not config.require_market_uptrend:
        return None
    market_symbol = config.market_filter_symbol.upper()
    if market_symbol not in data:
        return None
    market = data[market_symbol].copy().sort_index()
    slow = market["close"].rolling(config.market_filter_sma).mean()
    fast = market["close"].rolling(config.market_filter_fast_sma).mean()
    slow_rising = slow > slow.shift(config.market_slope_lookback)
    drawdown_pct = ((market["close"] / market["close"].rolling(config.market_drawdown_lookback).max()) - 1) * 100
    base = market["close"] > slow
    mode = str(config.market_filter_mode or "spy_above_sma").lower()
    if mode == "spy_above_rising_sma":
        return base & slow_rising
    if mode == "spy_drawdown_guard":
        return base & (drawdown_pct >= -abs(config.market_max_drawdown_pct))
    confirm_symbol = config.market_filter_confirm_symbol.upper()
    if mode in {"spy_qqq_above_sma", "risk_on_stack", "risk_on_strict"}:
        if confirm_symbol not in data:
            return base
        confirm = data[confirm_symbol].copy().sort_index()
        confirm_slow = confirm["close"].rolling(config.market_filter_sma).mean()
        confirm_fast = confirm["close"].rolling(config.market_filter_fast_sma).mean()
        confirm_ok = (confirm["close"] > confirm_slow).reindex(market.index).ffill().fillna(False)
        if mode == "spy_qqq_above_sma":
            return base & confirm_ok
        stack = base & confirm_ok & (fast > slow) & ((confirm_fast > confirm_slow).reindex(market.index).ffill().fillna(False))
        if mode == "risk_on_strict":
            return stack & slow_rising & (drawdown_pct >= -abs(config.market_max_drawdown_pct))
        return stack
    return base


def run_backtest(data: Dict[str, pd.DataFrame], config: BacktestConfig, verbose: bool = True) -> List[Trade]:
    trades: List[Trade] = []
    market_filter = market_filter_series(data, config)
    for symbol, df in data.items():
        symbol_trades = run_symbol_backtest(symbol, df, config, market_filter)
        trades.extend(symbol_trades)
        if verbose:
            print(f"{symbol}: {len(symbol_trades)} trade(s)")
    trades.sort(key=lambda trade: (trade.entry_date, trade.symbol))
    return trades


def parse_symbols(value: str) -> List[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def resolve_symbols(args: argparse.Namespace) -> Tuple[str, List[str]]:
    preset = str(getattr(args, "universe", "custom") or "custom").lower()
    if preset != "custom":
        if preset not in UNIVERSE_PRESETS:
            raise ValueError(f"unknown universe preset {preset}; choose one of {', '.join(sorted(UNIVERSE_PRESETS))}")
        return preset, UNIVERSE_PRESETS[preset]
    return "custom", parse_symbols(args.symbols)


def grid_configs(base: BacktestConfig, universe_names: List[str], full: bool = False) -> List[BacktestConfig]:
    reward_values = [1.0, 1.5, 2.0] if full else [1.5, 2.0]
    market_values = [False, True] if full else [True]
    stop_values = ["swing", "wider"] if full else ["swing", "wider"]
    pullback_values = [0.75, 1.25, 2.0] if full else [0.75, 1.25]
    hold_values = [10, 15, 20] if full else [15, 20]
    extension_values = [2.0, 3.0, 5.0] if full else [3.0, 5.0]
    recent_gain_values = [5.0, 8.0, 12.0] if full else [8.0]
    configs: List[BacktestConfig] = []
    for universe_name, reward_risk, market_filter, stop_mode, pullback, max_hold, max_extension, recent_gain in product(
        universe_names,
        reward_values,
        market_values,
        stop_values,
        pullback_values,
        hold_values,
        extension_values,
        recent_gain_values,
    ):
        configs.append(
            replace(
                base,
                universe_name=universe_name,
                reward_risk=reward_risk,
                require_market_uptrend=market_filter,
                stop_mode=stop_mode,
                pullback_tolerance_pct=pullback,
                max_hold_days=max_hold,
                max_extension_pct=max_extension,
                max_recent_gain_pct=recent_gain,
            )
        )
    return configs


def run_grid(data_by_universe: Dict[str, Dict[str, pd.DataFrame]], base_config: BacktestConfig, output_dir: Path, full: bool = False) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, object]] = []
    best_payload: Optional[Tuple[Dict[str, object], List[Trade], BacktestConfig]] = None
    configs = grid_configs(base_config, list(data_by_universe.keys()), full=full)
    total = len(configs)
    for idx, config in enumerate(configs, start=1):
        data = data_by_universe.get(config.universe_name, {})
        if not data:
            continue
        trades = run_backtest(data, config, verbose=False)
        summary = summarize(trades, config)
        score = research_score(summary)
        row = {
            "rank_score": score,
            "universe": config.universe_name,
            "symbols": ",".join(data.keys()),
            "reward_risk": config.reward_risk,
            "market_filter": config.require_market_uptrend,
            "stop_mode": config.stop_mode,
            "pullback_tolerance_pct": config.pullback_tolerance_pct,
            "max_hold_days": config.max_hold_days,
            "max_extension_pct": config.max_extension_pct,
            "max_recent_gain_pct": config.max_recent_gain_pct,
            "trade_count": summary["trade_count"],
            "win_rate": summary["win_rate"],
            "profit_factor": summary["profit_factor"],
            "net_pnl": summary["net_pnl"],
            "return_pct": summary["return_pct"],
            "max_drawdown_pct": summary["max_drawdown_pct"],
            "verdict": summary["verdict"],
        }
        rows.append(row)
        if best_payload is None or score > best_payload[0]["rank_score"]:
            best_payload = (row, trades, config)
        if idx % 50 == 0 or idx == total:
            print(f"Grid progress: {idx}/{total}")
    if not rows:
        return {
            "tested": 0,
            "leaderboard": "",
            "top10": "",
            "best_trades": "",
            "best_summary": "",
            "top": [],
            "message": "No grid rows produced. Check that loaded data matches the selected universe symbols.",
        }
    leaderboard = pd.DataFrame(rows).sort_values("rank_score", ascending=False)
    leaderboard_path = output_dir / "pmo_pullback_research_leaderboard.csv"
    leaderboard.head(250).to_csv(leaderboard_path, index=False)
    top_path = output_dir / "pmo_pullback_research_top10.json"
    top10 = leaderboard.head(10).to_dict(orient="records")
    top_path.write_text(json.dumps(top10, indent=2), encoding="utf-8")
    best_trades_path = output_dir / "pmo_pullback_research_best_trades.csv"
    best_summary_path = output_dir / "pmo_pullback_research_best_summary.json"
    if best_payload:
        _, best_trades, best_config = best_payload
        best_summary = summarize(best_trades, best_config)
        pd.DataFrame([asdict(trade) for trade in best_trades]).to_csv(best_trades_path, index=False)
        best_summary_path.write_text(json.dumps(best_summary, indent=2), encoding="utf-8")
    return {
        "tested": len(rows),
        "leaderboard": str(leaderboard_path),
        "top10": str(top_path),
        "best_trades": str(best_trades_path),
        "best_summary": str(best_summary_path),
        "top": top10[:5],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest PMO pullback-in-uptrend strategy.")
    parser.add_argument("--synthetic", action="store_true", help="Run built-in synthetic data smoke test.")
    parser.add_argument("--use-yfinance", action="store_true", help="Download daily bars with yfinance if installed.")
    parser.add_argument("--grid", action="store_true", help="Run parameter grid and write a research leaderboard.")
    parser.add_argument("--full-grid", action="store_true", help="Run the large grid. Slower, but broader.")
    parser.add_argument("--period", default="2y", help="yfinance period, default 2y.")
    parser.add_argument("--universe", default="custom", help=f"Universe preset: custom, {', '.join(sorted(UNIVERSE_PRESETS))}.")
    parser.add_argument("--grid-universes", default="default,index_tech,sector_etf", help="Comma-separated universe presets for --grid.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbols.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR), help="Folder with SYMBOL.csv OHLCV files.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Folder for trades CSV and summary JSON.")
    parser.add_argument("--risk", type=float, default=1.0, help="Risk percent of capital per trade.")
    parser.add_argument("--reward-risk", type=float, default=2.0, help="Target multiple of risk.")
    parser.add_argument("--max-hold-days", type=int, default=15, help="Maximum bars to hold.")
    parser.add_argument("--market-filter", action="store_true", help="Require SPY market uptrend for entries.")
    parser.add_argument("--market-filter-sma", type=int, default=200, help="SMA length for broad-market filter.")
    parser.add_argument("--stop-mode", choices=["swing", "atr", "wider", "tighter"], default="swing", help="Stop method.")
    parser.add_argument("--pullback-tolerance", type=float, default=1.25, help="Percent tolerance around fast SMA pullback.")
    parser.add_argument("--max-extension", type=float, default=3.0, help="Reject entries this far above fast SMA.")
    parser.add_argument("--max-recent-gain", type=float, default=8.0, help="Reject entries after this recent percent run.")
    args = parser.parse_args()

    universe_name, symbols = resolve_symbols(args)
    config = BacktestConfig(
        risk_per_trade_pct=args.risk,
        reward_risk=args.reward_risk,
        max_hold_days=args.max_hold_days,
        require_market_uptrend=args.market_filter,
        market_filter_sma=args.market_filter_sma,
        stop_mode=args.stop_mode,
        pullback_tolerance_pct=args.pullback_tolerance,
        max_extension_pct=args.max_extension,
        max_recent_gain_pct=args.max_recent_gain,
        universe_name=universe_name,
    )
    grid_universes = [name.strip().lower() for name in args.grid_universes.split(",") if name.strip()]
    if args.grid:
        bad = [name for name in grid_universes if name not in UNIVERSE_PRESETS]
        if bad:
            raise ValueError(f"unknown grid universe preset(s): {bad}")
        symbols_to_load = sorted({symbol for name in grid_universes for symbol in UNIVERSE_PRESETS[name]})
    else:
        symbols_to_load = symbols

    if args.synthetic:
        data = synthetic_data()
        print("Using synthetic smoke-test data.")
    elif args.use_yfinance:
        data = load_yfinance_data(symbols_to_load, args.period)
        print(f"Using yfinance data for {len(data)} symbol(s).")
    else:
        data = load_csv_data(Path(args.data_dir), symbols_to_load)
        print(f"Using CSV data from {args.data_dir} for {len(data)} symbol(s).")

    if not data:
        print("No data loaded. Use --synthetic, --use-yfinance, or add OHLCV CSV files to the data dir.")
        return 2

    if args.grid:
        data_by_universe = {
            name: {symbol: data[symbol] for symbol in UNIVERSE_PRESETS[name] if symbol in data}
            for name in grid_universes
        }
        result = run_grid(data_by_universe, config, Path(args.output_dir) / "research_grid", full=args.full_grid)
        print("\nPMO Pullback Research Grid")
        print(json.dumps(result, indent=2))
        return 0

    trades = run_backtest(data, config)
    summary = summarize(trades, config)
    trades_path, summary_path = save_outputs(trades, summary, Path(args.output_dir))
    print("\nPMO Pullback Backtest Summary")
    print(json.dumps({key: summary[key] for key in [
        "verdict",
        "trade_count",
        "wins",
        "losses",
        "win_rate",
        "profit_factor",
        "net_pnl",
        "return_pct",
        "max_drawdown_pct",
        "expectancy_usd",
    ]}, indent=2))
    print(f"\nTrades CSV: {trades_path}")
    print(f"Summary JSON: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
