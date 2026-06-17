from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo


MARKET_TZ = ZoneInfo("America/New_York")
OPEN_START = time(9, 30)
OPEN_END = time(10, 29, 59)
SUB_BUCKETS = [
    ("09:30-09:44", time(9, 30), time(9, 44, 59)),
    ("09:45-09:59", time(9, 45), time(9, 59, 59)),
    ("10:00-10:14", time(10, 0), time(10, 14, 59)),
    ("10:15-10:29", time(10, 15), time(10, 29, 59)),
]


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value).strip()
        if text.endswith("%"):
            text = text[:-1]
        return float(text)
    except Exception:
        return default


def first_value(row: Dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def parse_timestamp(row: Dict[str, Any]) -> Optional[datetime]:
    raw = first_value(row, "timestamp", "entry_timestamp", "entry_time", "filled_at", "time", "datetime", "created_at")
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


def outcome(row: Dict[str, Any]) -> str:
    status = first_value(row, "status", "result", "outcome", "quality").upper()
    pnl = as_float(first_value(row, "pnl", "pnl_usd", "realized_pnl", "profit_loss", "pnl_pct"), 0.0)
    if "WIN" in status or "PROFIT" in status or pnl > 0:
        return "WIN"
    if "LOSS" in status or pnl < 0:
        return "LOSS"
    return "OPEN"


def score_bucket(row: Dict[str, Any]) -> str:
    score = as_float(first_value(row, "score", "pmo_score"), 0.0)
    if score >= 85:
        return "85+"
    if score >= 75:
        return "75-84"
    if score >= 65:
        return "65-74"
    if score >= 55:
        return "55-64"
    if score > 0:
        return "1-54"
    return "UNKNOWN"


def pattern_key(row: Dict[str, Any]) -> str:
    return (
        first_value(row, "pattern_name", "setup_type", "setup", "strategy", "entry_pattern")
        or first_value(row, "fvg_signal", "orb_signal", "gap_signal")
        or "UNKNOWN"
    ).upper()


def sub_bucket_for(dt: datetime) -> str:
    current = dt.time()
    for label, start, end in SUB_BUCKETS:
        if start <= current <= end:
            return label
    return "OUTSIDE"


def init_bucket(label: str) -> Dict[str, Any]:
    return {"label": label, "trades": 0, "wins": 0, "losses": 0, "gross_win": 0.0, "gross_loss": 0.0, "pnl": 0.0, "rvol_values": []}


def add_trade(bucket: Dict[str, Any], row: Dict[str, Any], result: str) -> None:
    pnl = as_float(first_value(row, "pnl", "pnl_usd", "realized_pnl", "profit_loss", "pnl_pct"), 0.0)
    rvol = as_float(first_value(row, "relative_volume", "rvol"), 0.0)
    bucket["trades"] += 1
    bucket["pnl"] += pnl
    if rvol > 0:
        bucket["rvol_values"].append(rvol)
    if result == "WIN":
        bucket["wins"] += 1
        bucket["gross_win"] += max(0.0, pnl)
    elif result == "LOSS":
        bucket["losses"] += 1
        bucket["gross_loss"] += abs(min(0.0, pnl))


def finalize(bucket: Dict[str, Any]) -> Dict[str, Any]:
    trades = int(bucket.get("trades", 0))
    wins = int(bucket.get("wins", 0))
    losses = int(bucket.get("losses", 0))
    gross_loss = as_float(bucket.get("gross_loss"), 0.0)
    rvol_values = bucket.pop("rvol_values", [])
    bucket["pnl"] = round(as_float(bucket.get("pnl"), 0.0), 4)
    bucket["win_rate"] = round(wins / trades, 4) if trades else 0.0
    bucket["profit_factor"] = round(as_float(bucket.get("gross_win"), 0.0) / gross_loss, 4) if gross_loss > 0 else (999.0 if wins else 0.0)
    bucket["avg_rvol"] = round(sum(rvol_values) / len(rvol_values), 4) if rvol_values else 0.0
    bucket["losses"] = losses
    return bucket


def sorted_buckets(grouped: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [finalize(dict(value)) for value in grouped.values()]
    rows.sort(key=lambda item: (item.get("trades", 0), item.get("win_rate", 0), item.get("profit_factor", 0)), reverse=True)
    return rows


def analyze_journal(path: Path) -> Dict[str, Any]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    opening_rows: List[Dict[str, Any]] = []
    by_sub = {label: init_bucket(label) for label, _, _ in SUB_BUCKETS}
    by_symbol: Dict[str, Dict[str, Any]] = {}
    by_score: Dict[str, Dict[str, Any]] = {}
    by_pattern: Dict[str, Dict[str, Any]] = {}
    rvol_by_result = {"WIN": [], "LOSS": []}

    for row in rows:
        result = outcome(row)
        if result not in {"WIN", "LOSS"}:
            continue
        dt = parse_timestamp(row)
        if not dt or not (OPEN_START <= dt.time() <= OPEN_END):
            continue
        opening_rows.append(row)
        add_trade(by_sub[sub_bucket_for(dt)], row, result)
        symbol = first_value(row, "symbol", "ticker") or "UNKNOWN"
        add_trade(by_symbol.setdefault(symbol.upper(), init_bucket(symbol.upper())), row, result)
        band = score_bucket(row)
        add_trade(by_score.setdefault(band, init_bucket(band)), row, result)
        pattern = pattern_key(row)
        add_trade(by_pattern.setdefault(pattern, init_bucket(pattern)), row, result)
        rvol = as_float(first_value(row, "relative_volume", "rvol"), 0.0)
        if rvol > 0:
            rvol_by_result[result].append(rvol)

    overall = init_bucket("09:30-10:29")
    for row in opening_rows:
        add_trade(overall, row, outcome(row))
    summary = finalize(overall)
    win_rvol = rvol_by_result["WIN"]
    loss_rvol = rvol_by_result["LOSS"]
    return {
        "ok": True,
        "source_file": str(path),
        "opening_window": summary,
        "sub_windows": [finalize(dict(by_sub[label])) for label, _, _ in SUB_BUCKETS],
        "symbols": sorted_buckets(by_symbol),
        "score_bands": sorted_buckets(by_score),
        "patterns": sorted_buckets(by_pattern),
        "rvol": {
            "wins_avg": round(sum(win_rvol) / len(win_rvol), 4) if win_rvol else 0.0,
            "losses_avg": round(sum(loss_rvol) / len(loss_rvol), 4) if loss_rvol else 0.0,
            "wins_count": len(win_rvol),
            "losses_count": len(loss_rvol),
        },
        "recommendations": [
            "Compare sub_windows first; if 09:45-09:59 carries the edge, tighten earlier/later slots.",
            "For 09:30-09:59, test PMO_OPENING_MIN_RVOL at 2.0 before increasing trade count.",
            "Prefer GAP_UP_HOLD and ORB BULLISH confirmations for opening long entries.",
        ],
    }


def print_table(title: str, rows: Iterable[Dict[str, Any]], limit: int = 12) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for row in list(rows)[:limit]:
        print(
            f"{row.get('label'):<18} trades={row.get('trades', 0):>3} "
            f"W={row.get('wins', 0):>3} L={row.get('losses', 0):>3} "
            f"WR={row.get('win_rate', 0):>6.1%} PF={row.get('profit_factor', 0):>7} "
            f"avgRVOL={row.get('avg_rvol', 0):>5}"
        )


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: python pmo_analysis.py pmo_csv\\pmo_bot_trade_journal.csv")
        return 2
    path = Path(argv[1])
    if not path.exists():
        print(f"Journal not found: {path}")
        return 1
    report = analyze_journal(path)
    summary = report["opening_window"]
    print(f"PMO opening-window journal analysis: {path}")
    print(
        f"09:30-10:29: trades={summary['trades']} W={summary['wins']} L={summary['losses']} "
        f"WR={summary['win_rate']:.1%} PF={summary['profit_factor']} avgRVOL={summary['avg_rvol']}"
    )
    print_table("Sub-windows", report["sub_windows"])
    print_table("Symbols", report["symbols"])
    print_table("Score bands", report["score_bands"])
    print_table("Patterns", report["patterns"])
    print("\nRVOL wins vs losses")
    print("-------------------")
    print(json.dumps(report["rvol"], indent=2))
    output = Path("pmo_reports") / "pmo_opening_window_analysis_latest.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
