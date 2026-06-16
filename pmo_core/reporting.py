from __future__ import annotations

import csv
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_json_file(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def write_json_file(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, default=str))


def recent_csv_rows(path: Path, limit: int = 8) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as handle:
            return list(csv.DictReader(handle))[-limit:]
    except Exception:
        return []


def csv_append(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    fieldnames = list(row.keys())
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def report_file_rows(*folders: Path, limit: int = 80) -> List[Dict[str, Any]]:
    candidates = []
    for folder in folders:
        if folder.exists():
            for suffix in ("*.json", "*.csv", "*.log", "*.txt", "*.html"):
                candidates.extend(folder.glob(suffix))
    rows = []
    for path in sorted(set(candidates), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)[:limit]:
        rows.append({"name": path.name, "path": str(path), "kind": path.suffix.lstrip("."), "size": path.stat().st_size, "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat()})
    return rows
