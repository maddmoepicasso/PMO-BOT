from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import BASE_DIR


DEFAULT_RESPONSE = (
    "Nothing is necessarily wrong. Closed records are often hidden by filters, permissions, "
    "date range, or sync settings. I'll check whether we are pulling active-only data or full historical data."
)

CHECKLIST = [
    "Confirm the correct data source is connected.",
    "Confirm archived, closed, completed, and historical records are included in sync.",
    "Confirm the user has permission to view closed records.",
    "Check whether a date filter is hiding older records.",
    "Check whether the dashboard is showing only active/open items.",
    "Check whether the API integration is pulling live records only instead of full history.",
    "Check whether vector memory has indexed closed records.",
    "Confirm the correct workspace, project, broker, account, and environment are selected.",
    "Check whether records were deleted, archived, expired, or never synced.",
    "Run a manual refresh, re-sync, or permissions update if needed.",
]

HISTORICAL_KEYWORDS = [
    "closed thread", "closed threads", "closed trade", "closed trades", "closed record", "closed records",
    "archived", "archive", "completed task", "completed tasks", "historical", "history",
    "old record", "old records", "can't see closed", "cannot see closed", "missing closed",
    "deleted record", "deleted records", "unavailable records", "past conversations",
]

OPEN_KEYWORDS = ["open records", "open threads", "open trades", "active items", "active records"]


@dataclass
class RecordSource:
    name: str
    kind: str
    path: Path


SOURCES = [
    RecordSource("trade_journal", "trades", BASE_DIR / "pmo_csv" / "pmo_bot_trade_journal.csv"),
    RecordSource("stock_order_journal", "trades", BASE_DIR / "pmo_csv" / "pmo_order_execution_journal.csv"),
    RecordSource("crypto_order_journal", "trades", BASE_DIR / "pmo_csv" / "pmo_crypto_order_execution_journal.csv"),
    RecordSource("why_not_events", "historical_activity", BASE_DIR / "pmo_csv" / "pmo_why_not_events.csv"),
    RecordSource("watchlist_history", "historical_activity", BASE_DIR / "pmo_csv" / "pmo_auto_watchlist_history.csv"),
    RecordSource("button_audit", "audit", BASE_DIR / "pmo_csv" / "pmo_bot_button_audit.csv"),
    RecordSource("payment_events", "audit", BASE_DIR / "pmo_csv" / "pmo_payment_events.csv"),
]


def is_historical_records_request(message: str) -> bool:
    text = message.lower()
    return any(k in text for k in HISTORICAL_KEYWORDS) or (
        any(k in text for k in ["closed", "archived", "completed", "historical", "history"]) and
        any(k in text for k in ["thread", "trade", "task", "record", "conversation", "item", "log"])
    )


def is_open_records_request(message: str) -> bool:
    text = message.lower()
    return any(k in text for k in OPEN_KEYWORDS)


def _read_rows(path: Path, limit: int = 25000) -> tuple[list[dict[str, Any]], str]:
    if not path.exists():
        return [], "missing"
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as handle:
            rows = []
            for idx, row in enumerate(csv.DictReader(handle)):
                if idx >= limit:
                    break
                rows.append(dict(row))
        return rows, "connected"
    except Exception as exc:
        return [], f"error: {exc}"


def _status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or row.get("order_status") or row.get("state") or "UNKNOWN").upper()
        counts[status] = counts.get(status, 0) + 1
    return counts


def _classify_status(status: str) -> str:
    s = status.upper()
    if s.endswith("_OPEN") or s in {"OPEN_FILLED", "CLOSE_SUBMITTED", "TARGET_REACHED_OPEN", "STOP_REACHED_OPEN", "MAX_HOLD_EXIT_DUE_OPEN"}:
        return "open"
    if any(k in s for k in ["CLOSED", "FILLED_CLOSED", "TAKE_PROFIT", "STOP", "EXIT", "DONE", "COMPLETE", "COMPLETED"]):
        return "closed"
    if any(k in s for k in ["ARCHIVE", "ARCHIVED"]):
        return "archived"
    if any(k in s for k in ["DELETE", "DELETED", "EXPIRED", "UNAVAILABLE"]):
        return "unavailable"
    if any(k in s for k in ["OPEN", "PENDING", "SUBMITTED", "ACTIVE"]):
        return "open"
    return "historical"


def summarize_source(source: RecordSource) -> dict[str, Any]:
    rows, connection = _read_rows(source.path)
    counts = {"open": 0, "closed": 0, "archived": 0, "unavailable": 0, "historical": 0}
    status_counts = _status_counts(rows)
    for status, count in status_counts.items():
        counts[_classify_status(status)] += count
    last_imported = None
    if source.path.exists():
        last_imported = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(source.path.stat().st_mtime))
    excluded_reason = ""
    if connection == "missing":
        excluded_reason = "Source file is missing or has not synced yet."
    elif rows and counts["closed"] == 0 and source.kind == "trades":
        excluded_reason = "No closed trade outcomes found in this source yet; open/pending records are present or history may need sync."
    return {
        "name": source.name,
        "kind": source.kind,
        "path": str(source.path),
        "connection": connection,
        "total_rows": len(rows),
        "counts": counts,
        "status_counts": status_counts,
        "last_imported": last_imported,
        "included_in_history": connection == "connected",
        "excluded_reason": excluded_reason,
    }


def diagnose_records(scope: str = "all", include_deleted: bool = True) -> dict[str, Any]:
    scope = (scope or "all").lower()
    selected = [s for s in SOURCES if scope in {"all", s.kind, s.name} or (scope == "trades" and s.kind == "trades")]
    sources = [summarize_source(source) for source in selected]
    totals = {"open": 0, "closed": 0, "archived": 0, "unavailable": 0, "historical": 0, "rows": 0}
    for source in sources:
        totals["rows"] += int(source["total_rows"])
        for key in ["open", "closed", "archived", "unavailable", "historical"]:
            totals[key] += int(source["counts"].get(key, 0))
    findings = []
    if not sources:
        findings.append("No matching record sources are registered for this scope.")
    if any(s["connection"] == "connected" for s in sources):
        findings.append("At least one historical data source is connected.")
    if totals["closed"] == 0:
        findings.append("Closed records are not currently visible in the inspected sources.")
    if totals["open"] > 0 and totals["closed"] == 0:
        findings.append("Open records are present, so the dashboard may be showing active-only data or closed outcomes have not synced yet.")
    if totals["unavailable"] and not include_deleted:
        findings.append("Deleted/unavailable records exist but may be hidden by source permissions or policy.")
    return {
        "default_response": DEFAULT_RESPONSE,
        "scope": scope,
        "include_deleted_requested": include_deleted,
        "totals": totals,
        "sources": sources,
        "checklist": CHECKLIST,
        "findings": findings,
        "manual_resync_recommended": totals["closed"] == 0,
        "audit": {
            "diagnosed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source_count": len(sources),
            "import_visibility": "full-history-capable; source permissions and sync settings still apply",
        },
    }


def diagnostic_text(diagnostic: dict[str, Any]) -> str:
    totals = diagnostic.get("totals", {})
    lines = [
        diagnostic.get("default_response", DEFAULT_RESPONSE),
        "",
        "Record visibility diagnostic:",
        f"- Open: {totals.get('open', 0)}",
        f"- Closed: {totals.get('closed', 0)}",
        f"- Archived: {totals.get('archived', 0)}",
        f"- Unavailable/deleted/expired: {totals.get('unavailable', 0)}",
        f"- Historical/other: {totals.get('historical', 0)}",
        f"- Total rows inspected: {totals.get('rows', 0)}",
        "",
        "Checks to run:",
    ]
    lines.extend(f"{idx}. {item}" for idx, item in enumerate(diagnostic.get("checklist", CHECKLIST), start=1))
    findings = diagnostic.get("findings") or []
    if findings:
        lines.append("")
        lines.append("Current findings:")
        lines.extend(f"- {item}" for item in findings)
    if diagnostic.get("manual_resync_recommended"):
        lines.append("")
        lines.append("Recommended next action: run a manual refresh/re-sync and confirm closed/history records are included by the source permissions.")
    return "\n".join(lines)
