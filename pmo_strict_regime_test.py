"""
PMO Strict Regime Test

Compares market-regime filters across robustness windows. This is the decision
gate after the plain SPY 200MA test failed durability.

Research only. No orders.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List

import pandas as pd

from pmo_pullback_backtest import (
    BacktestConfig,
    DEFAULT_OUTPUT_DIR,
    UNIVERSE_PRESETS,
    load_yfinance_data,
    run_backtest,
    summarize,
)
from pmo_robustness_test import DEFAULT_WINDOWS, durability_verdict, slice_data


REGIME_MODES = [
    "spy_above_sma",
    "spy_above_rising_sma",
    "spy_drawdown_guard",
    "spy_qqq_above_sma",
    "risk_on_stack",
    "risk_on_strict",
]


def config_for_mode(mode: str) -> BacktestConfig:
    return BacktestConfig(
        universe_name="index_tech",
        reward_risk=1.5,
        require_market_uptrend=True,
        market_filter_mode=mode,
        market_filter_sma=200,
        market_filter_fast_sma=50,
        market_slope_lookback=20,
        market_drawdown_lookback=63,
        market_max_drawdown_pct=10.0,
        stop_mode="wider",
        pullback_tolerance_pct=1.25,
        max_hold_days=15,
        max_extension_pct=5.0,
        max_recent_gain_pct=8.0,
    )


def run_mode(data: Dict[str, pd.DataFrame], mode: str) -> Dict[str, object]:
    config = config_for_mode(mode)
    rows: List[Dict[str, object]] = []
    for name, start, end in DEFAULT_WINDOWS:
        window_data = slice_data(data, start, end)
        trades = run_backtest(window_data, config, verbose=False)
        summary = summarize(trades, config)
        rows.append({
            "mode": mode,
            "window": name,
            "start": start,
            "end": end,
            "trade_count": summary["trade_count"],
            "wins": summary["wins"],
            "losses": summary["losses"],
            "win_rate": summary["win_rate"],
            "profit_factor": summary["profit_factor"],
            "net_pnl": summary["net_pnl"],
            "return_pct": summary["return_pct"],
            "max_drawdown_pct": summary["max_drawdown_pct"],
            "verdict": summary["verdict"],
        })
    judged = [row for row in rows if int(row["trade_count"]) >= 20]
    positive = [row for row in judged if float(row["net_pnl"]) > 0 and float(row["profit_factor"]) >= 1.1]
    worst_pf = min([float(row["profit_factor"]) for row in judged], default=0)
    worst_dd = max([float(row["max_drawdown_pct"]) for row in judged], default=0)
    total_trades = sum(int(row["trade_count"]) for row in rows)
    total_pnl = sum(float(row["net_pnl"]) for row in rows)
    return {
        "mode": mode,
        "durability_verdict": durability_verdict(rows),
        "judged_windows": len(judged),
        "positive_windows": len(positive),
        "total_trades": total_trades,
        "total_pnl": round(total_pnl, 2),
        "worst_profit_factor": round(worst_pf, 3),
        "worst_drawdown_pct": round(worst_dd, 2),
        "config": asdict(config),
        "windows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare strict PMO regime filters across historical windows.")
    parser.add_argument("--period", default="max", help="yfinance period.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR / "strict_regime"))
    args = parser.parse_args()

    symbols = sorted(set(UNIVERSE_PRESETS["index_tech"] + ["QQQ", "SPY"]))
    data = load_yfinance_data(symbols, args.period)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    reports = [run_mode(data, mode) for mode in REGIME_MODES]
    leaderboard = []
    window_rows = []
    for report in reports:
        leaderboard.append({
            "mode": report["mode"],
            "durability_verdict": report["durability_verdict"],
            "judged_windows": report["judged_windows"],
            "positive_windows": report["positive_windows"],
            "total_trades": report["total_trades"],
            "total_pnl": report["total_pnl"],
            "worst_profit_factor": report["worst_profit_factor"],
            "worst_drawdown_pct": report["worst_drawdown_pct"],
        })
        window_rows.extend(report["windows"])
    leaderboard = sorted(
        leaderboard,
        key=lambda row: (
            row["durability_verdict"] == "DURABLE_ENOUGH_FOR_FORWARD_PAPER_TEST",
            row["positive_windows"],
            row["worst_profit_factor"],
            -row["worst_drawdown_pct"],
            row["total_pnl"],
        ),
        reverse=True,
    )
    report_payload = {"ok": True, "leaderboard": leaderboard, "reports": reports}
    (output_dir / "pmo_strict_regime_report.json").write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    pd.DataFrame(leaderboard).to_csv(output_dir / "pmo_strict_regime_leaderboard.csv", index=False)
    pd.DataFrame(window_rows).to_csv(output_dir / "pmo_strict_regime_windows.csv", index=False)

    print("\nPMO Strict Regime Test")
    print(json.dumps({
        "top": leaderboard[:6],
        "report": str(output_dir / "pmo_strict_regime_report.json"),
        "leaderboard": str(output_dir / "pmo_strict_regime_leaderboard.csv"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
