from __future__ import annotations

import csv
import datetime as dt
from typing import Dict, Iterable


def parse_csv_trades(
    path: str,
    ts_col: str = "ts",
    price_col: str = "price",
    qty_col: str = "qty",
    side_col: str = "side",
) -> Iterable[Dict[str, float | str]]:
    """Convert a trade CSV into MarketSimulator trade ticks.

    Expected output:
    {"ts": float_epoch_seconds, "price": float, "qty": float, "side": "buy"|"sell"}
    """
    with open(path, "r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw_ts = row.get(ts_col, "")
            try:
                ts = float(raw_ts)
            except ValueError:
                parsed = dt.datetime.fromisoformat(raw_ts)
                ts = parsed.timestamp()

            side = str(row.get(side_col) or "buy").strip().lower()
            if side not in {"buy", "sell"}:
                side = "buy"

            yield {
                "ts": ts,
                "price": float(row.get(price_col, 0) or 0),
                "qty": float(row.get(qty_col, row.get("size", 0)) or 0),
                "side": side,
            }
