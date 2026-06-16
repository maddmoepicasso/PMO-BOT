from __future__ import annotations

from typing import Any, Dict, List


def route_rows(app: Any) -> List[Dict[str, Any]]:
    rows = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r.rule)):
        rows.append({"rule": str(rule.rule), "endpoint": str(rule.endpoint), "methods": sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})})
    return rows
