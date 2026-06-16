from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, List

V206_MODULES = [
    "pmo_core.paths",
    "pmo_core.environment",
    "pmo_core.settings_switchboard",
    "pmo_core.reporting",
    "pmo_core.security",
    "pmo_core.market_data",
    "pmo_core.execution_guard",
    "pmo_core.proof_center",
    "pmo_core.tradingview_bridge",
    "pmo_core.dashboard_context",
    "pmo_core.route_registry",
    "pmo_core.payments",
    "pmo_core.storage",
    "pmo_core.agent",
    "pmo_core.v2055_hardening",
]


def v206_module_report(base_dir: Path | str = ".") -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for module in V206_MODULES:
        spec = importlib.util.find_spec(module)
        rows.append({"module": module, "ready": spec is not None, "origin": getattr(spec, "origin", "") if spec else ""})
    ready = sum(1 for row in rows if row["ready"])
    return {"ok": ready == len(rows), "ready_count": ready, "total_count": len(rows), "modules": rows}
