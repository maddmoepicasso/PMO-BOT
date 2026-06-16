from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def init_pmo_storage(db_path: Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pmo_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time TEXT,
                source_file TEXT,
                payload_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pmo_system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time TEXT,
                event_type TEXT,
                status TEXT,
                detail TEXT,
                payload_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time TEXT,
                event_type TEXT,
                status TEXT,
                detail TEXT,
                payload_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pmo_paper_outcomes (
                trade_id TEXT PRIMARY KEY,
                updated_at TEXT,
                payload_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_outcomes (
                trade_id TEXT PRIMARY KEY,
                updated_at TEXT,
                symbol TEXT,
                result TEXT,
                rules_followed INTEGER,
                pnl_pct REAL,
                payload_json TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def sqlite_append_event(db_path: Path, source_file: Path, row: Dict[str, Any], event_time: str = "") -> None:
    init_pmo_storage(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO pmo_events(event_time, source_file, payload_json) VALUES (?, ?, ?)",
            (event_time or datetime.utcnow().isoformat(), str(source_file), json.dumps(row, default=str)),
        )
        conn.commit()
    finally:
        conn.close()


def sqlite_append_system_event(db_path: Path, event_type: str, status: str, detail: str = "", payload: Dict[str, Any] | None = None, event_time: str = "") -> None:
    init_pmo_storage(db_path)
    values = (
        event_time or datetime.utcnow().isoformat(),
        str(event_type),
        str(status),
        str(detail),
        json.dumps(payload or {}, default=str),
    )
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO pmo_system_events(event_time, event_type, status, detail, payload_json) VALUES (?, ?, ?, ?, ?)",
            values,
        )
        conn.execute(
            "INSERT INTO system_events(event_time, event_type, status, detail, payload_json) VALUES (?, ?, ?, ?, ?)",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def sqlite_table_counts(db_path: Path) -> Dict[str, int]:
    init_pmo_storage(db_path)
    counts: Dict[str, int] = {}
    conn = sqlite3.connect(db_path)
    try:
        for table in ("pmo_events", "pmo_system_events", "pmo_paper_outcomes"):
            try:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except Exception:
                counts[table] = 0
    finally:
        conn.close()
    return counts


def sqlite_upsert_paper_outcome(db_path: Path, row: Dict[str, Any], updated_at: str = "") -> None:
    init_pmo_storage(db_path)
    trade_id = str(row.get("trade_id") or row.get("replay_id") or row.get("id") or "").strip()
    if not trade_id:
        raise ValueError("paper outcome row requires trade_id, replay_id, or id")
    updated = updated_at or datetime.utcnow().isoformat()
    row_created_at = (
        row.get("created_at")
        or row.get("timestamp")
        or row.get("entry_time")
        or row.get("reviewed_at")
        or updated
    )
    payload = json.dumps(row, default=str)
    result = str(row.get("result") or row.get("win_loss_result") or row.get("quality") or row.get("outcome") or "").strip().upper()
    rules_followed = 1 if bool(row.get("rules_followed")) else 0
    try:
        pnl_pct = float(row.get("pnl_pct", row.get("profit_loss_pct", row.get("pnl_percent", 0))) or 0)
    except Exception:
        pnl_pct = 0.0
    try:
        entry_price = float(row.get("entry_price") or 0)
    except Exception:
        entry_price = 0.0
    try:
        stop_loss = float(row.get("stop_loss") or row.get("stop_loss_price") or 0)
    except Exception:
        stop_loss = 0.0
    try:
        take_profit = float(row.get("take_profit") or row.get("take_profit_price") or 0)
    except Exception:
        take_profit = 0.0
    try:
        exit_price = float(row.get("exit_price") or 0)
    except Exception:
        exit_price = 0.0
    try:
        pnl_usd = float(row.get("pnl_usd") or row.get("profit_loss_usd") or row.get("pnl") or 0)
    except Exception:
        pnl_usd = 0.0
    try:
        score_at_entry = float(row.get("score_at_entry") or row.get("pmo_score") or row.get("score") or 0)
    except Exception:
        score_at_entry = 0.0
    conn = sqlite3.connect(db_path)
    try:
        pmo_columns = {str(item[1]) for item in conn.execute("PRAGMA table_info(pmo_paper_outcomes)").fetchall()}
        if "created_at" in pmo_columns:
            conn.execute(
                """
                INSERT INTO pmo_paper_outcomes(trade_id, created_at, updated_at, payload_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(trade_id) DO UPDATE SET
                    created_at=COALESCE(pmo_paper_outcomes.created_at, excluded.created_at),
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (trade_id, row_created_at, updated, payload),
            )
        else:
            conn.execute(
                """
                INSERT INTO pmo_paper_outcomes(trade_id, updated_at, payload_json)
                VALUES (?, ?, ?)
                ON CONFLICT(trade_id) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json
                """,
                (trade_id, updated, payload),
            )

        paper_columns = {str(item[1]) for item in conn.execute("PRAGMA table_info(paper_outcomes)").fetchall()}
        paper_values = {
            "trade_id": trade_id,
            "created_at": row_created_at,
            "closed_at": row.get("closed_at") or row.get("reviewed_at") or "",
            "symbol": str(row.get("symbol") or "").strip().upper(),
            "market": str(row.get("market") or row.get("asset_class") or "").strip().upper(),
            "side": str(row.get("side") or row.get("direction") or "").strip().upper(),
            "strategy": str(row.get("strategy") or row.get("setup_type") or row.get("setup") or "").strip(),
            "setup_type": str(row.get("setup_type") or row.get("setup") or "").strip(),
            "entry_reason": str(row.get("entry_reason") or row.get("why") or "").strip(),
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "exit_price": exit_price,
            "exit_reason": str(row.get("exit_reason") or row.get("outcome") or "").strip(),
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "result": result,
            "market_regime": str(row.get("market_regime") or "").strip(),
            "volatility_condition": str(row.get("volatility_condition") or row.get("volatility") or "").strip(),
            "score_at_entry": score_at_entry,
            "gates": str(row.get("gates") or row.get("rule_followed_detail") or "").strip(),
            "rules_followed": rules_followed,
            "source": str(row.get("source") or row.get("replay_type") or "PMO_V112").strip() or "PMO_V112",
            "payload_json": payload,
            "updated_at": updated,
        }
        preferred_columns = [
            "trade_id", "created_at", "closed_at", "updated_at", "symbol", "market", "side",
            "strategy", "setup_type", "entry_reason", "entry_price", "stop_loss", "take_profit",
            "exit_price", "exit_reason", "pnl_usd", "pnl_pct", "result", "market_regime",
            "volatility_condition", "score_at_entry", "gates", "rules_followed", "source", "payload_json",
        ]
        insert_columns = [column for column in preferred_columns if column in paper_columns]
        update_columns = [column for column in insert_columns if column != "trade_id"]
        update_sql = ",\n                    ".join(
            f"{column}=COALESCE(paper_outcomes.{column}, excluded.{column})" if column == "created_at" else f"{column}=excluded.{column}"
            for column in update_columns
        )
        conn.execute(
            f"""
            INSERT INTO paper_outcomes({", ".join(insert_columns)})
            VALUES ({", ".join("?" for _ in insert_columns)})
            ON CONFLICT(trade_id) DO UPDATE SET
                {update_sql}
            """,
            tuple(paper_values[column] for column in insert_columns),
        )
        conn.commit()
    finally:
        conn.close()
