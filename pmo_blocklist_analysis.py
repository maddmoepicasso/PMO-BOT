"""
PMO Symbol Blocklist + Clean Dataset Analysis + R:R Calibration
===============================================================

Run:
    python pmo_blocklist_analysis.py pmo_csv/pmo_bot_trade_journal.csv

This is a local research utility. It reads CSV data only, prints diagnostics,
and never places orders or changes PMO settings.
"""

from __future__ import annotations

import csv
import os
import random
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, time
from typing import Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo


BLOCKLIST_DEFAULTS = ["HOOD", "PSQ", "RWM", "CVX"]
MARKET_TZ = ZoneInfo("America/New_York")
OPENING_DAMAGE_START = time(9, 30)
OPENING_DAMAGE_END = time(9, 44, 59)


def load_csv(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _pnl(row: Dict[str, str]) -> float:
    for key in ("pnl", "pnl_usd", "profit_loss", "realized_pnl", "return_pct", "pct_gain", "gain_pct"):
        value = row.get(key, "")
        if value not in (None, "", "N/A"):
            try:
                return float(value)
            except Exception:
                pass
    return 0.0


def _won(row: Dict[str, str]) -> bool:
    for key in ("outcome", "result", "trade_result", "status"):
        value = row.get(key, "").upper()
        if "WIN" in value or "PROFIT" in value:
            return True
        if "LOSS" in value or "LOSE" in value:
            return False
    return _pnl(row) > 0


def _closed(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    output = []
    for row in rows:
        for key in ("outcome", "result", "trade_result", "status"):
            value = row.get(key, "").upper()
            if any(token in value for token in ("CLOSED", "WIN", "LOSS")):
                output.append(row)
                break
        else:
            if _pnl(row) != 0:
                output.append(row)
    return output


def _ticker(row: Dict[str, str]) -> str:
    return (row.get("ticker") or row.get("symbol") or "?").strip().upper()


def _first(row: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _timestamp_et(row: Dict[str, str]) -> Optional[datetime]:
    raw = _first(row, "timestamp", "entry_timestamp", "entry_time", "filled_at", "time", "datetime", "created_at")
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo:
        return parsed.astimezone(MARKET_TZ)
    return parsed


def _in_opening_damage_slot(row: Dict[str, str]) -> bool:
    timestamp = _timestamp_et(row)
    if not timestamp:
        return False
    return OPENING_DAMAGE_START <= timestamp.time() <= OPENING_DAMAGE_END


def _median(values: List[float]) -> float:
    sorted_values = sorted(values)
    if not sorted_values:
        return 0.0
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2


def _pf(wins: List[Dict[str, str]], losses: List[Dict[str, str]]) -> float:
    gross_win = sum(_pnl(row) for row in wins)
    gross_loss = abs(sum(_pnl(row) for row in losses))
    return round(gross_win / gross_loss, 3) if gross_loss else float("inf")


def stats_block(rows: List[Dict[str, str]], label: str) -> Dict[str, float]:
    if not rows:
        print(f"  {label}: no trades")
        return {}
    wins = [row for row in rows if _won(row)]
    losses = [row for row in rows if not _won(row)]
    win_pnls = [_pnl(row) for row in wins]
    loss_pnls = [_pnl(row) for row in losses]
    all_pnls = [_pnl(row) for row in rows]
    total = len(rows)
    win_rate = len(wins) / total * 100
    profit_factor = _pf(wins, losses)
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0
    net = sum(all_pnls)
    rr = abs(avg_win / avg_loss) if avg_loss else 0
    expectancy = (len(wins) / total * avg_win) + (len(losses) / total * avg_loss)

    print(f"\n  -- {label} --")
    print(f"  Trades     : {total} ({len(wins)}W / {len(losses)}L)")
    print(f"  Win rate   : {win_rate:.1f}% {'PASS' if win_rate >= 52 else 'FAIL'} (need 52%)")
    print(f"  Prof factor: {profit_factor:.3f} {'PASS' if profit_factor >= 1.25 else 'FAIL'} (need 1.25)")
    print(f"  Avg win    : ${avg_win:+.2f}")
    print(f"  Avg loss   : ${avg_loss:+.2f}")
    print(f"  R:R ratio  : {rr:.2f} {'PASS' if rr >= 1.0 else 'FAIL'} (need >=1.0)")
    print(f"  Expectancy : ${expectancy:+.3f}/trade")
    print(f"  Net P&L    : ${net:+.2f}")
    return {
        "n": total,
        "wins": len(wins),
        "losses": len(losses),
        "wr": win_rate,
        "pf": profit_factor,
        "aw": avg_win,
        "al": avg_loss,
        "rr": rr,
        "expectancy": expectancy,
        "net": net,
    }


def rr_calibration(rows: List[Dict[str, str]]) -> None:
    wins = [row for row in rows if _won(row)]
    losses = [row for row in rows if not _won(row)]
    if not wins or not losses:
        return

    median_win = _median([abs(_pnl(row)) for row in wins])
    median_loss = _median([abs(_pnl(row)) for row in losses])
    win_rate = len(wins) / len(rows)

    print(f"\n{'=' * 68}")
    print("  3. R:R CALIBRATION ANALYSIS")
    print(f"{'=' * 68}")
    print(f"  Current median win : ${median_win:.2f}")
    print(f"  Current median loss: ${median_loss:.2f}")
    print(f"  Current R:R        : {median_win / median_loss:.2f}" if median_loss else "  Current R:R        : n/a")
    print(f"  Current win rate   : {win_rate * 100:.1f}%")

    print("\n  Breakeven win rate at each R:R target:")
    print(f"  {'R:R':>6}  {'Need WR%':>9}  {'Current WR':>12}  {'At 50% WR':>10}  {'At 55% WR':>10}")
    print(f"  {'-' * 56}")
    for rr in (0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5):
        breakeven_wr = 1 / (1 + rr) * 100

        def sim_pf(wr_pct: float, rr_value: float) -> float:
            wr_decimal = wr_pct / 100
            return round((wr_decimal * rr_value) / ((1 - wr_decimal) * 1.0), 3) if (1 - wr_decimal) > 0 else float("inf")

        flag = " <-- target" if rr == 1.5 else ""
        print(f"  {rr:>6.2f}  {breakeven_wr:>8.1f}%  {sim_pf(win_rate * 100, rr):>12.3f}  {sim_pf(50, rr):>10.3f}  {sim_pf(55, rr):>10.3f}{flag}")

    rr_needed = 1.25 * (1 - win_rate) / win_rate if win_rate else float("inf")
    print("\n  What needs to change to hit WR>=52% + PF>=1.25:")
    print("  ------------------------------------------------")
    print(f"  At current {win_rate * 100:.1f}% win rate:")
    print(f"    Need R:R >= {rr_needed:.2f} to reach PF 1.25")
    if median_loss:
        print(f"    If median loss stays at ${median_loss:.2f}: median win needs to be ${median_loss * rr_needed:.2f}+")

    print("\n  Scenario A - tighten stops:")
    for stop_mult in (0.5, 0.6, 0.7, 0.8):
        new_loss = median_loss * stop_mult
        new_rr = median_win / new_loss if new_loss else 0
        new_pf = (win_rate * median_win) / ((1 - win_rate) * new_loss) if new_loss else 0
        print(f"    Stop at {stop_mult * 100:.0f}% of current -> R:R {new_rr:.2f} -> PF {new_pf:.3f} {'PASS' if new_pf >= 1.25 else ''}")

    print("\n  Scenario B - extend targets:")
    for target_mult in (1.25, 1.5, 1.75, 2.0):
        new_win = median_win * target_mult
        new_rr = new_win / median_loss if median_loss else 0
        new_pf = (win_rate * new_win) / ((1 - win_rate) * median_loss) if median_loss else 0
        print(f"    TP at {target_mult * 100:.0f}% of current -> R:R {new_rr:.2f} -> PF {new_pf:.3f} {'PASS' if new_pf >= 1.25 else ''}")

    print("\n  Scenario C - both:")
    for stop_mult, target_mult in ((0.7, 1.5), (0.6, 1.5), (0.7, 1.75), (0.6, 1.75)):
        new_loss = median_loss * stop_mult
        new_win = median_win * target_mult
        new_rr = new_win / new_loss if new_loss else 0
        new_pf = (win_rate * new_win) / ((1 - win_rate) * new_loss) if new_loss else 0
        print(f"    Stop {stop_mult * 100:.0f}% / TP {target_mult * 100:.0f}% -> R:R {new_rr:.2f} -> PF {new_pf:.3f} {'PASS' if new_pf >= 1.25 else ''}")

    print("\n  Current PMO theoretical settings:")
    print("    Stop: 4.0%  TP: 6.0%  Trailing: 2.0% -> theoretical R:R: 1.50")
    print("    If realized R:R is much lower, trailing exits may be cutting winners short.")


def _score_band(row: Dict[str, str]) -> str:
    for key in ("score", "pmo_score", "entry_score"):
        try:
            value = float(row.get(key, ""))
            if value < 65:
                return "50-64"
            if value < 78:
                return "65-77"
            if value < 88:
                return "78-87"
            return "88+"
        except Exception:
            pass
    return "unknown"


def analyze(path: str) -> None:
    all_rows = load_csv(path)
    closed = _closed(all_rows)

    print(f"\n{'=' * 68}")
    print("  PMO BLOCKLIST + CLEAN DATASET + R:R ANALYSIS")
    print(f"{'=' * 68}")
    print(f"  File  : {os.path.basename(path)}")
    print(f"  Total : {len(all_rows)} rows | Closed: {len(closed)}")

    print(f"\n{'=' * 68}")
    print("  1. SYMBOL DAMAGE REPORT")
    print(f"{'=' * 68}")
    by_ticker = defaultdict(list)
    for row in closed:
        by_ticker[_ticker(row)].append(row)

    print(f"\n  {'Symbol':<12} {'N':>4} {'W':>4} {'L':>4} {'WR%':>6} {'PF':>6} {'Net$':>8}  Status")
    print(f"  {'-' * 60}")
    for symbol, rows in sorted(by_ticker.items(), key=lambda item: sum(_pnl(row) for row in item[1])):
        wins = [row for row in rows if _won(row)]
        losses = [row for row in rows if not _won(row)]
        count = len(rows)
        win_rate = len(wins) / count * 100 if count else 0
        profit_factor = _pf(wins, losses)
        net = sum(_pnl(row) for row in rows)
        flag = " <-- BLOCKLIST" if symbol in BLOCKLIST_DEFAULTS else (" PASS" if win_rate >= 52 and profit_factor >= 1.25 else "")
        if count >= 3 or symbol in BLOCKLIST_DEFAULTS:
            print(f"  {symbol:<12} {count:>4} {len(wins):>4} {len(losses):>4} {win_rate:>5.1f}% {profit_factor:>6.3f} {net:>+8.2f}{flag}")

    print(f"\n{'=' * 68}")
    print("  2. CLEAN DATASET ANALYSIS")
    print(f"{'=' * 68}")
    print(f"  Blocklist: {BLOCKLIST_DEFAULTS}")

    blocked = [row for row in closed if _ticker(row) in BLOCKLIST_DEFAULTS]
    clean = [row for row in closed if _ticker(row) not in BLOCKLIST_DEFAULTS]
    opening_damage = [row for row in closed if _in_opening_damage_slot(row)]
    clean_opening_damage = [row for row in clean if _in_opening_damage_slot(row)]
    clean_without_opening_damage = [row for row in clean if not _in_opening_damage_slot(row)]
    stats_block(closed, f"FULL dataset ({len(closed)} trades)")
    stats_block(blocked, f"BLOCKED symbols only ({len(blocked)} trades)")
    stats_block(clean, f"CLEAN dataset ex-blocklist ({len(clean)} trades)")
    stats_block(opening_damage, f"09:30-09:44 ET slot ({len(opening_damage)} trades)")
    stats_block(clean_opening_damage, f"CLEAN overlap inside 09:30-09:44 ET ({len(clean_opening_damage)} trades)")
    stats_block(clean_without_opening_damage, f"CLEAN ex-blocklist and ex-09:30-09:44 ET ({len(clean_without_opening_damage)} trades)")

    print("\n  Score bands (CLEAN dataset only):")
    print(f"  {'Band':<10} {'N':>4} {'W':>4} {'L':>4} {'WR%':>6} {'PF':>6} {'Expect':>8}")
    print(f"  {'-' * 48}")
    band_groups = defaultdict(list)
    for row in clean:
        band_groups[_score_band(row)].append(row)
    for band in ("50-64", "65-77", "78-87", "88+", "unknown"):
        rows = band_groups.get(band, [])
        if not rows:
            continue
        wins = [row for row in rows if _won(row)]
        losses = [row for row in rows if not _won(row)]
        count = len(rows)
        win_rate = len(wins) / count * 100
        profit_factor = _pf(wins, losses)
        avg_win = sum(_pnl(row) for row in wins) / len(wins) if wins else 0
        avg_loss = sum(_pnl(row) for row in losses) / len(losses) if losses else 0
        expectancy = (len(wins) / count * avg_win) + (len(losses) / count * avg_loss)
        flag = " PASS" if win_rate >= 52 and profit_factor >= 1.25 else ""
        print(f"  {band:<10} {count:>4} {len(wins):>4} {len(losses):>4} {win_rate:>5.1f}% {profit_factor:>6.3f} {expectancy:>+8.3f}{flag}")

    rr_calibration(clean)

    print(f"\n{'=' * 68}")
    print("  BLOCKLIST RECOMMENDATION")
    print(f"{'=' * 68}")
    print("  Current default PMO_SYMBOL_BLOCKLIST target:")
    for symbol in BLOCKLIST_DEFAULTS:
        print(f"    - {symbol}")


def _demo() -> None:
    random.seed(42)
    symbols = (
        ["AAPL"] * 8 + ["NVDA"] * 8 + ["TSLA"] * 8 + ["META"] * 6
        + ["HOOD"] * 19 + ["PSQ"] * 6 + ["RWM"] * 5 + ["CVX"] * 3
        + ["MSFT"] * 8 + ["AMD"] * 8 + ["XLP"] * 5 + ["DOGE/USD"] * 4
    )
    rows = []
    for index, symbol in enumerate(symbols):
        won = random.random() < (0.1 if symbol in BLOCKLIST_DEFAULTS else 0.5)
        pnl = random.uniform(0.4, 2.5) if won else random.uniform(-2.5, -0.5)
        rows.append({
            "ticker": symbol,
            "score": round(random.uniform(65, 87), 1),
            "pnl": round(pnl, 2),
            "outcome": "CLOSED_WIN" if won else "CLOSED_LOSS",
            "entry_time": f"2026-01-{(index % 20) + 1:02d} 10:30:00",
        })
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    writer = csv.DictWriter(tmp, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    tmp.close()
    try:
        analyze(tmp.name)
    finally:
        os.unlink(tmp.name)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pmo_blocklist_analysis.py path/to/pmo_bot_trade_journal.csv")
        print("\nRunning with synthetic demo data...\n")
        _demo()
    else:
        analyze(sys.argv[1])
