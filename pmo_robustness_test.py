"""
PMO Pullback Robustness Test

Runs the best current pullback strategy across separate historical windows.
This answers whether the strategy is durable or only looked good in one regime.

Research only. No broker calls. No orders.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from typing import Dict, List

import pandas as pd

from pmo_pullback_backtest import (
    BacktestConfig,
    DEFAULT_DATA_DIR,
    DEFAULT_OUTPUT_DIR,
    UNIVERSE_PRESETS,
    load_csv_data,
    load_yfinance_data,
    run_backtest,
    summarize,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_WINDOWS = [
    ("2014_2016", "2014-01-01", "2016-12-31"),
    ("2017_2019", "2017-01-01", "2019-12-31"),
    ("2020_2021", "2020-01-01", "2021-12-31"),
    ("2022_2024", "2022-01-01", "2024-12-31"),
    ("2025_NOW", "2025-01-01", date.today().isoformat()),
]


def slice_data(data: Dict[str, pd.DataFrame], start: str, end: str) -> Dict[str, pd.DataFrame]:
    sliced: Dict[str, pd.DataFrame] = {}
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    for symbol, frame in data.items():
        if frame.empty:
            continue
        local = frame.copy()
        local.index = pd.to_datetime(local.index)
        local = local[(local.index >= start_ts) & (local.index <= end_ts)]
        if len(local) >= 260:
            sliced[symbol] = local
    return sliced


def durability_verdict(rows: List[Dict[str, object]]) -> str:
    judged = [row for row in rows if int(row.get("trade_count", 0)) >= 20]
    if len(judged) < 3:
        return "INSUFFICIENT_HISTORY"
    positive = [row for row in judged if float(row.get("net_pnl", 0)) > 0 and float(row.get("profit_factor", 0)) >= 1.1]
    strong = [row for row in judged if float(row.get("profit_factor", 0)) >= 1.3 and float(row.get("max_drawdown_pct", 999)) <= 15]
    if len(positive) == len(judged) and len(strong) >= max(2, len(judged) - 1):
        return "DURABLE_ENOUGH_FOR_FORWARD_PAPER_TEST"
    if len(positive) >= max(2, len(judged) - 1):
        return "MOSTLY_DURABLE_BUT_NEEDS_FILTER_REVIEW"
    return "NOT_DURABLE"


def run_robustness(data: Dict[str, pd.DataFrame], config: BacktestConfig, output_dir: Path) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, object]] = []
    for name, start, end in DEFAULT_WINDOWS:
        window_data = slice_data(data, start, end)
        trades = run_backtest(window_data, config, verbose=False)
        summary = summarize(trades, config)
        row = {
            "window": name,
            "start": start,
            "end": end,
            "symbols": ",".join(window_data.keys()),
            "trade_count": summary["trade_count"],
            "wins": summary["wins"],
            "losses": summary["losses"],
            "win_rate": summary["win_rate"],
            "profit_factor": summary["profit_factor"],
            "net_pnl": summary["net_pnl"],
            "return_pct": summary["return_pct"],
            "max_drawdown_pct": summary["max_drawdown_pct"],
            "verdict": summary["verdict"],
        }
        rows.append(row)
        trades_path = output_dir / f"pmo_robustness_{name}_trades.csv"
        pd.DataFrame([asdict(trade) for trade in trades]).to_csv(trades_path, index=False)
    verdict = durability_verdict(rows)
    report = {
        "ok": True,
        "strategy": "PMO pullback in uptrend, SPY 200MA regime, index-tech universe",
        "durability_verdict": verdict,
        "config": asdict(config),
        "windows": rows,
    }
    (output_dir / "pmo_robustness_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame(rows).to_csv(output_dir / "pmo_robustness_windows.csv", index=False)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Test PMO pullback strategy durability across historical windows.")
    parser.add_argument("--use-yfinance", action="store_true", help="Download history with yfinance instead of local CSV.")
    parser.add_argument("--period", default="max", help="yfinance period.")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR / "robustness"))
    args = parser.parse_args()

    symbols = UNIVERSE_PRESETS["index_tech"]
    config = BacktestConfig(
        universe_name="index_tech",
        reward_risk=1.5,
        require_market_uptrend=True,
        market_filter_sma=200,
        stop_mode="wider",
        pullback_tolerance_pct=1.25,
        max_hold_days=15,
        max_extension_pct=5.0,
        max_recent_gain_pct=8.0,
    )
    if args.use_yfinance:
        data = load_yfinance_data(symbols, args.period)
    else:
        data = load_csv_data(Path(args.data_dir), symbols)
    if not data:
        print("No data loaded. Run pmo_historical_data_downloader.py first or pass --use-yfinance.")
        return 2
    report = run_robustness(data, config, Path(args.output_dir))
    print("\nPMO Robustness Test")
    print(json.dumps({
        "durability_verdict": report["durability_verdict"],
        "windows": report["windows"],
        "report": str(Path(args.output_dir) / "pmo_robustness_report.json"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
