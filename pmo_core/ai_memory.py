"""Small JSON memory helpers for PMO Desk Commander AI."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def load_ai_memory(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"events": [], "summary": {}, "updated": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"events": [], "summary": {}, "updated": ""}
    except Exception:
        return {"events": [], "summary": {}, "updated": ""}


def save_ai_memory(path: Path, memory: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(memory, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def append_ai_memory_event(path: Path, event: Dict[str, Any], limit: int = 300) -> Dict[str, Any]:
    memory = load_ai_memory(path)
    events: List[Dict[str, Any]] = memory.get("events") if isinstance(memory.get("events"), list) else []
    clean_event = dict(event)
    clean_event.setdefault("timestamp", datetime.now().isoformat())
    events.append(clean_event)
    memory["events"] = events[-limit:]
    memory["updated"] = clean_event["timestamp"]
    memory["summary"] = {
        "event_count": len(memory["events"]),
        "last_type": clean_event.get("event_type") or clean_event.get("type") or "",
        "last_status": clean_event.get("status") or "",
    }
    save_ai_memory(path, memory)
    return memory

