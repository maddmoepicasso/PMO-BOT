"""
PMO Historical Data Downloader

Downloads daily OHLCV bars into pmo_csv/backtest_daily_bars so
pmo_pullback_backtest.py can run from stable local CSV files.

Source priority:
1. Alpaca official market data API, using existing PMO .env keys.
2. Tiingo EOD API, if TIINGO_API_KEY is configured.
3. Alpha Vantage daily adjusted API, if ALPHA_VANTAGE_API_KEY is configured.
4. yfinance fallback for quick research only.

This tool is research-only. It does not place trades.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
DEFAULT_DATA_DIR = ROOT / "pmo_csv" / "backtest_daily_bars"
DEFAULT_REPORT_DIR = ROOT / "pmo_reports" / "backtests"
DEFAULT_SYMBOLS = [
    "SPY", "QQQ", "XLK", "XLY", "XLF", "XLV",
    "AAPL", "MSFT", "NVDA", "AMD", "META", "AMZN", "TSLA", "JPM",
]
ALPACA_STOCK_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"


def load_env(path: Path = ENV_FILE) -> Dict[str, str]:
    env = dict(os.environ)
    if not path.exists():
        return env
    for raw_line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        clean = value.strip().strip('"').strip("'")
        env[key.strip()] = clean
    return env


def env_first(env: Dict[str, str], names: Iterable[str]) -> str:
    for name in names:
        value = str(env.get(name, "")).strip()
        if value:
            return value
    return ""


def parse_symbols(value: str) -> List[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def iso_date_days_back(days: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=max(1, days))).isoformat()


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
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
    if "date" not in df.columns:
        df = df.reset_index().rename(columns={"index": "date"})
    needed = ["date", "open", "high", "low", "close", "volume"]
    for col in needed:
        if col not in df.columns:
            df[col] = ""
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype(str)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"])
    return df[needed].sort_values("date").drop_duplicates(subset=["date"], keep="last")


def write_symbol_csv(symbol: str, rows: List[Dict[str, Any]], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_symbol = symbol.replace("/", "_").replace("\\", "_")
    path = output_dir / f"{safe_symbol}.csv"
    frame = normalize_frame(pd.DataFrame(rows))
    frame.to_csv(path, index=False)
    return path


def fetch_alpaca(symbols: List[str], start: str, end: str, env: Dict[str, str], output_dir: Path) -> Dict[str, Any]:
    key = env_first(env, ["APCA_API_KEY_ID", "ALPACA_API_KEY_ID", "ALPACA_KEY_ID", "ALPACA_API_KEY"])
    secret = env_first(env, ["APCA_API_SECRET_KEY", "ALPACA_API_SECRET_KEY", "ALPACA_SECRET_KEY", "ALPACA_API_SECRET"])
    if not key or not secret:
        return {"ok": False, "source": "alpaca", "error": "missing Alpaca API key/secret in .env", "written": []}
    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
    }
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "1Day",
        "start": f"{start}T00:00:00Z",
        "end": f"{end}T23:59:59Z",
        "adjustment": "all",
        "feed": env.get("PMO_ALPACA_DATA_FEED", "iex").lower(),
        "limit": 10000,
    }
    bars_by_symbol: Dict[str, List[Dict[str, Any]]] = {symbol: [] for symbol in symbols}
    page_token = ""
    while True:
        request_params = dict(params)
        if page_token:
            request_params["page_token"] = page_token
        response = requests.get(ALPACA_STOCK_BARS_URL, headers=headers, params=request_params, timeout=40)
        if response.status_code >= 300:
            return {
                "ok": False,
                "source": "alpaca",
                "status_code": response.status_code,
                "error": response.text[:500],
                "written": [],
            }
        payload = response.json()
        raw_bars = payload.get("bars") or {}
        for symbol, rows in raw_bars.items():
            for row in rows or []:
                bars_by_symbol.setdefault(symbol.upper(), []).append({
                    "date": row.get("t"),
                    "open": row.get("o"),
                    "high": row.get("h"),
                    "low": row.get("l"),
                    "close": row.get("c"),
                    "volume": row.get("v"),
                })
        page_token = str(payload.get("next_page_token") or "")
        if not page_token:
            break
    written = []
    for symbol, rows in bars_by_symbol.items():
        if rows:
            path = write_symbol_csv(symbol, rows, output_dir)
            written.append({"symbol": symbol, "rows": len(rows), "file": str(path)})
    return {"ok": bool(written), "source": "alpaca", "written": written, "symbols_requested": symbols}


def fetch_tiingo(symbols: List[str], start: str, end: str, env: Dict[str, str], output_dir: Path) -> Dict[str, Any]:
    token = env_first(env, ["TIINGO_API_KEY", "TIINGO_TOKEN"])
    if not token:
        return {"ok": False, "source": "tiingo", "error": "missing TIINGO_API_KEY", "written": []}
    written = []
    errors = []
    for symbol in symbols:
        url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices"
        params = {"startDate": start, "endDate": end, "format": "json", "resampleFreq": "daily"}
        response = requests.get(url, headers={"Authorization": f"Token {token}"}, params=params, timeout=40)
        if response.status_code >= 300:
            errors.append(f"{symbol}: HTTP {response.status_code}")
            continue
        rows = [
            {
                "date": row.get("date"),
                "open": row.get("adjOpen", row.get("open")),
                "high": row.get("adjHigh", row.get("high")),
                "low": row.get("adjLow", row.get("low")),
                "close": row.get("adjClose", row.get("close")),
                "volume": row.get("adjVolume", row.get("volume")),
            }
            for row in response.json()
        ]
        if rows:
            path = write_symbol_csv(symbol, rows, output_dir)
            written.append({"symbol": symbol, "rows": len(rows), "file": str(path)})
        time.sleep(0.2)
    return {"ok": bool(written), "source": "tiingo", "written": written, "errors": errors[:10]}


def fetch_alpha_vantage(symbols: List[str], env: Dict[str, str], output_dir: Path) -> Dict[str, Any]:
    key = env_first(env, ["ALPHA_VANTAGE_API_KEY", "ALPHAVANTAGE_API_KEY"])
    if not key:
        return {"ok": False, "source": "alpha_vantage", "error": "missing ALPHA_VANTAGE_API_KEY", "written": []}
    written = []
    errors = []
    for symbol in symbols:
        params = {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": symbol,
            "outputsize": "full",
            "apikey": key,
        }
        response = requests.get("https://www.alphavantage.co/query", params=params, timeout=60)
        if response.status_code >= 300:
            errors.append(f"{symbol}: HTTP {response.status_code}")
            continue
        payload = response.json()
        series = payload.get("Time Series (Daily)", {})
        if not series:
            errors.append(f"{symbol}: no daily series")
            continue
        rows = [
            {
                "date": day,
                "open": row.get("1. open"),
                "high": row.get("2. high"),
                "low": row.get("3. low"),
                "close": row.get("5. adjusted close", row.get("4. close")),
                "volume": row.get("6. volume"),
            }
            for day, row in series.items()
        ]
        path = write_symbol_csv(symbol, rows, output_dir)
        written.append({"symbol": symbol, "rows": len(rows), "file": str(path)})
        time.sleep(12)
    return {"ok": bool(written), "source": "alpha_vantage", "written": written, "errors": errors[:10]}


def fetch_yfinance(symbols: List[str], period: str, output_dir: Path) -> Dict[str, Any]:
    try:
        import yfinance as yf
    except Exception as exc:
        return {"ok": False, "source": "yfinance", "error": f"yfinance missing: {exc}", "written": []}
    written = []
    errors = []
    for symbol in symbols:
        try:
            frame = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False)
            if frame is None or frame.empty:
                errors.append(f"{symbol}: no data")
                continue
            if isinstance(frame.columns, pd.MultiIndex):
                frame = frame.copy()
                frame.columns = [str(col[0]).strip() if isinstance(col, tuple) else str(col).strip() for col in frame.columns]
            frame = frame.reset_index()
            path = write_symbol_csv(symbol, frame.to_dict(orient="records"), output_dir)
            written.append({"symbol": symbol, "rows": len(frame), "file": str(path)})
        except Exception as exc:
            errors.append(f"{symbol}: {str(exc)[:120]}")
    return {"ok": bool(written), "source": "yfinance", "written": written, "errors": errors[:10]}


def write_manifest(report: Dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "pmo_historical_data_manifest.json"
    safe = dict(report)
    path.write_text(json.dumps(safe, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Download historical OHLCV bars for PMO backtests.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbols.")
    parser.add_argument("--source", choices=["auto", "alpaca", "tiingo", "alpha_vantage", "yfinance"], default="auto")
    parser.add_argument("--years", type=float, default=5.0, help="Years of history for date-range APIs.")
    parser.add_argument("--start", default="", help="Start date YYYY-MM-DD. Overrides --years.")
    parser.add_argument("--end", default=date.today().isoformat(), help="End date YYYY-MM-DD.")
    parser.add_argument("--period", default="5y", help="yfinance period when using yfinance.")
    parser.add_argument("--output-dir", default=str(DEFAULT_DATA_DIR), help="CSV output folder.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Manifest output folder.")
    args = parser.parse_args()

    symbols = parse_symbols(args.symbols)
    start = args.start or iso_date_days_back(int(args.years * 365.25))
    end = args.end
    env = load_env()
    output_dir = Path(args.output_dir)
    sources = [args.source] if args.source != "auto" else ["alpaca", "tiingo", "alpha_vantage", "yfinance"]

    attempts = []
    result: Optional[Dict[str, Any]] = None
    for source in sources:
        print(f"Trying {source} historical data for {len(symbols)} symbol(s)...")
        if source == "alpaca":
            attempt = fetch_alpaca(symbols, start, end, env, output_dir)
        elif source == "tiingo":
            attempt = fetch_tiingo(symbols, start, end, env, output_dir)
        elif source == "alpha_vantage":
            attempt = fetch_alpha_vantage(symbols, env, output_dir)
        else:
            attempt = fetch_yfinance(symbols, args.period, output_dir)
        attempts.append(attempt)
        print(json.dumps({k: v for k, v in attempt.items() if k != "written"}, indent=2))
        if attempt.get("ok"):
            result = attempt
            break

    report = {
        "ok": bool(result and result.get("ok")),
        "selected_source": result.get("source") if result else "",
        "symbols": symbols,
        "start": start,
        "end": end,
        "output_dir": str(output_dir),
        "written": result.get("written", []) if result else [],
        "attempts": attempts,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    manifest = write_manifest(report, Path(args.report_dir))
    print("\nHistorical Data Manifest")
    print(json.dumps({
        "ok": report["ok"],
        "selected_source": report["selected_source"],
        "written_count": len(report["written"]),
        "output_dir": report["output_dir"],
        "manifest": str(manifest),
    }, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
