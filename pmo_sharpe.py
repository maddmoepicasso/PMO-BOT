"""
PMO risk-adjusted performance metrics.

Standalone:
    python pmo_sharpe.py pmo_csv/pmo_bot_trade_journal.csv
    python pmo_sharpe.py pmo_csv/pmo_bot_trade_journal.csv --json-output pmo_reports/pmo_risk_adjusted_metrics.json

Import:
    from pmo_sharpe import analyze_file, compute_risk_metrics
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


DEFAULT_BLOCKLIST = {"HOOD", "PSQ", "RWM", "CVX"}
TRADES_PER_YEAR_ESTIMATE = 252 * 2


def _load_pmo_blocklist() -> set[str]:
    try:
        from pmo_settings import PMO_SYMBOL_BLOCKLIST  # type: ignore

        return {str(x).strip().upper() for x in PMO_SYMBOL_BLOCKLIST if str(x).strip()}
    except Exception:
        return set(DEFAULT_BLOCKLIST)


def load_csv(path: str | os.PathLike[str]) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _float(row: Dict[str, Any], keys: Sequence[str], default: float = 0.0) -> float:
    for key in keys:
        value = row.get(key)
        if value in (None, "", "N/A", "None"):
            continue
        try:
            return float(str(value).replace("$", "").replace("%", "").replace(",", "").strip())
        except Exception:
            continue
    return default


def _symbol(row: Dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or row.get("asset") or "?").strip().upper()


def _status(row: Dict[str, Any]) -> str:
    return str(row.get("status") or row.get("outcome") or row.get("result") or row.get("trade_result") or "").upper()


def _pnl(row: Dict[str, Any]) -> float:
    return _float(row, ("pnl", "profit_loss", "realized_pnl", "closed_pnl", "net_pnl"), 0.0)


def _closed_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    closed: List[Dict[str, Any]] = []
    for row in rows:
        status = _status(row)
        if "CLOSED_WIN" in status or "CLOSED_LOSS" in status:
            closed.append(row)
        elif ("CLOSED" in status or "WIN" in status or "LOSS" in status) and _symbol(row) not in {"SYSTEM", ""}:
            closed.append(row)
        elif _pnl(row) != 0.0 and "OPEN" not in status and _symbol(row) not in {"SYSTEM", ""}:
            closed.append(row)
    return closed


def _won(row: Dict[str, Any]) -> bool:
    status = _status(row)
    if "WIN" in status or "PROFIT" in status:
        return True
    if "LOSS" in status or "LOSE" in status:
        return False
    return _pnl(row) > 0


def _max_drawdown(values: Sequence[float]) -> Dict[str, Any]:
    cumulative: List[float] = []
    running = 0.0
    for value in values:
        running += value
        cumulative.append(running)

    if not cumulative:
        return {"max_drawdown": 0.0, "start_index": 0, "end_index": 0, "equity_curve": []}

    peak = cumulative[0]
    peak_index = 0
    max_dd = 0.0
    max_start = 0
    max_end = 0
    for index, value in enumerate(cumulative):
        if value > peak:
            peak = value
            peak_index = index
        drawdown = peak - value
        if drawdown > max_dd:
            max_dd = drawdown
            max_start = peak_index
            max_end = index
    return {
        "max_drawdown": round(max_dd, 4),
        "start_index": max_start,
        "end_index": max_end,
        "equity_curve": [round(x, 4) for x in cumulative],
    }


def compute_risk_metrics(
    rows: Sequence[Dict[str, Any]],
    label: str = "dataset",
    blocklist: Optional[set[str]] = None,
    risk_free_per_trade: float = 0.0,
) -> Dict[str, Any]:
    filtered = [row for row in rows if _symbol(row) not in (blocklist or set())]
    closed = _closed_rows(filtered)
    if len(closed) < 3:
        return {
            "ok": False,
            "label": label,
            "error": f"Too few closed trades for risk metrics: {len(closed)}",
            "n": len(closed),
        }

    pnls = [_pnl(row) for row in closed]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    n = len(pnls)
    mean_pnl = sum(pnls) / n
    net_pnl = sum(pnls)
    variance = sum((pnl - mean_pnl) ** 2 for pnl in pnls) / (n - 1)
    std_pnl = math.sqrt(variance) if variance > 0 else 0.0
    sharpe = ((mean_pnl - risk_free_per_trade) / std_pnl) if std_pnl else 0.0
    sharpe_annual = sharpe * math.sqrt(TRADES_PER_YEAR_ESTIMATE)

    downside = [pnl for pnl in pnls if pnl < risk_free_per_trade]
    if downside:
        downside_variance = sum((pnl - risk_free_per_trade) ** 2 for pnl in downside) / len(downside)
        downside_std = math.sqrt(downside_variance)
        sortino = ((mean_pnl - risk_free_per_trade) / downside_std) if downside_std else 0.0
    else:
        sortino = 999.0

    drawdown = _max_drawdown(pnls)
    max_dd = float(drawdown["max_drawdown"])
    annualized_pnl_estimate = mean_pnl * TRADES_PER_YEAR_ESTIMATE
    calmar = annualized_pnl_estimate / max_dd if max_dd > 0 else 999.0
    recovery = net_pnl / max_dd if max_dd > 0 else 999.0

    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_win / gross_loss if gross_loss else 999.0
    win_rate = len(wins) / n
    avg_win = gross_win / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    expectancy = (win_rate * avg_win) + ((1.0 - win_rate) * avg_loss)

    max_win_streak = 0
    max_loss_streak = 0
    current_win = 0
    current_loss = 0
    for row in closed:
        if _won(row):
            current_win += 1
            current_loss = 0
            max_win_streak = max(max_win_streak, current_win)
        else:
            current_loss += 1
            current_win = 0
            max_loss_streak = max(max_loss_streak, current_loss)

    mae_values = [_float(row, ("mae", "max_adverse_excursion"), 0.0) for row in closed if row.get("mae") or row.get("max_adverse_excursion")]
    mfe_values = [_float(row, ("mfe", "max_favorable_excursion"), 0.0) for row in closed if row.get("mfe") or row.get("max_favorable_excursion")]

    return {
        "ok": True,
        "label": label,
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "win_rate_pct": round(win_rate * 100.0, 2),
        "net_pnl": round(net_pnl, 4),
        "mean_pnl": round(mean_pnl, 4),
        "std_pnl": round(std_pnl, 4),
        "profit_factor": round(profit_factor, 4),
        "sharpe": round(sharpe, 4),
        "sharpe_annual_estimate": round(sharpe_annual, 4),
        "sortino": round(sortino, 4),
        "calmar": round(calmar, 4),
        "max_drawdown": round(max_dd, 4),
        "recovery_factor": round(recovery, 4),
        "expectancy": round(expectancy, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "reward_risk": round(abs(avg_win / avg_loss), 4) if avg_loss else 999.0,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "avg_mae": round(sum(mae_values) / len(mae_values), 4) if mae_values else None,
        "avg_mfe": round(sum(mfe_values) / len(mfe_values), 4) if mfe_values else None,
        "drawdown_start_index": drawdown["start_index"],
        "drawdown_end_index": drawdown["end_index"],
        "risk_free_per_trade": risk_free_per_trade,
    }


def analyze_rows(rows: Sequence[Dict[str, Any]], blocklist: Optional[set[str]] = None) -> Dict[str, Any]:
    blocklist = blocklist if blocklist is not None else _load_pmo_blocklist()
    closed = _closed_rows(rows)
    return {
        "ok": True,
        "source": "pmo_sharpe",
        "blocklist": sorted(blocklist),
        "total_rows": len(rows),
        "closed_rows": len(closed),
        "full": compute_risk_metrics(closed, "FULL_REAL_TRADE_JOURNAL", set()),
        "clean": compute_risk_metrics(closed, "CLEAN_EX_BLOCKLIST", blocklist),
    }


def analyze_file(path: str | os.PathLike[str]) -> Dict[str, Any]:
    return analyze_rows(load_csv(path))


def _fmt_money(value: Any) -> str:
    try:
        return f"${float(value):+.2f}"
    except Exception:
        return str(value)


def print_report(report: Dict[str, Any]) -> None:
    print("PMO RISK-ADJUSTED METRICS")
    print("=" * 72)
    print(f"Rows: {report.get('total_rows')} | Closed rows: {report.get('closed_rows')}")
    print(f"Clean blocklist: {', '.join(report.get('blocklist', []))}")
    print()

    for key in ("full", "clean"):
        metrics = report.get(key, {})
        print(metrics.get("label", key).replace("_", " "))
        print("-" * 72)
        if not metrics.get("ok"):
            print(metrics.get("error", "No metrics available"))
            print()
            continue
        print(f"Trades: {metrics['n']} ({metrics['wins']}W / {metrics['losses']}L) | WR {metrics['win_rate_pct']}%")
        print(f"Net PnL: {_fmt_money(metrics['net_pnl'])} | PF {metrics['profit_factor']} | Expectancy {_fmt_money(metrics['expectancy'])}")
        print(f"Sharpe: {metrics['sharpe']} | Annual estimate {metrics['sharpe_annual_estimate']} | Sortino {metrics['sortino']}")
        print(f"Max DD: {_fmt_money(metrics['max_drawdown'])} | Recovery {metrics['recovery_factor']} | Calmar {metrics['calmar']}")
        print(f"Avg win: {_fmt_money(metrics['avg_win'])} | Avg loss: {_fmt_money(metrics['avg_loss'])} | R:R {metrics['reward_risk']}")
        print(f"Streaks: win {metrics['max_win_streak']} | loss {metrics['max_loss_streak']}")
        if metrics.get("avg_mae") is not None:
            print(f"Avg MAE: {_fmt_money(metrics['avg_mae'])} | Avg MFE: {_fmt_money(metrics['avg_mfe'])}")
        else:
            print("Avg MAE/MFE: not available in closed journal rows")
        print()

    clean = report.get("clean", {})
    full = report.get("full", {})
    if clean.get("ok") and full.get("ok"):
        print("FULL VS CLEAN DELTA")
        print("-" * 72)
        for field in ("sharpe", "sortino", "profit_factor", "max_drawdown", "recovery_factor", "expectancy"):
            delta = float(clean.get(field, 0.0)) - float(full.get(field, 0.0))
            print(f"{field:22s} full={full.get(field):>10} clean={clean.get(field):>10} delta={delta:+.4f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="PMO risk-adjusted metrics report")
    parser.add_argument("csv_path", help="Path to pmo_bot_trade_journal.csv")
    parser.add_argument("--json-output", default="", help="Optional path for dashboard-ready JSON output")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    args = parser.parse_args()

    report = analyze_file(args.csv_path)
    if args.json_output:
        out_path = Path(args.json_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
