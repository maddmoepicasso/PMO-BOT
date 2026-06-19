from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any


class PMOAIStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pmoai_cache (
                    cache_key TEXT PRIMARY KEY,
                    request TEXT NOT NULL,
                    response TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pmoai_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    detail TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pmoai_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    detail TEXT NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def cache_key(message: str, route: dict[str, Any]) -> str:
        payload = json.dumps({"message": message.strip(), "route": route}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_cache(self, key: str) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM pmoai_cache WHERE cache_key=?", (key,)).fetchone()
        if not row:
            return None
        return {
            "provider": row["provider"],
            "response": json.loads(row["response"]),
            "created_at": row["created_at"],
        }

    def put_cache(self, key: str, request: str, provider: str, response: dict[str, Any]) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO pmoai_cache(cache_key, request, response, provider, created_at) VALUES(?,?,?,?,?)",
                (key, request, json.dumps(response), provider, time.time()),
            )
            conn.commit()

    def log_usage(self, provider: str, model: str, task_type: str, status: str, latency_ms: int, detail: str = "", estimated_cost: float = 0) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                "INSERT INTO pmoai_usage(timestamp, provider, model, task_type, status, estimated_cost, latency_ms, detail) VALUES(?,?,?,?,?,?,?,?)",
                (time.time(), provider, model, task_type, status, estimated_cost, latency_ms, detail[:400]),
            )
            conn.commit()

    def log_audit(self, action: str, actor: str, provider: str, detail: str) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                "INSERT INTO pmoai_audit(timestamp, action, actor, provider, detail) VALUES(?,?,?,?,?)",
                (time.time(), action, actor, provider, detail[:600]),
            )
            conn.commit()

    def usage_summary(self, limit: int = 40) -> dict[str, Any]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT provider, model, task_type, status, estimated_cost, latency_ms, datetime(timestamp, 'unixepoch') AS ts FROM pmoai_usage ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            totals = conn.execute(
                "SELECT provider, COUNT(*) AS calls, SUM(estimated_cost) AS cost FROM pmoai_usage GROUP BY provider"
            ).fetchall()
        return {
            "recent": [dict(row) for row in rows],
            "totals": [dict(row) for row in totals],
        }
