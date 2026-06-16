from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

PMO_V2055_EXTRA_ADMIN_POST_PATHS = {
    "/api/trading-optimization/report",
    "/api/full-system-test",
    "/api/system/integrity",
    "/api/v106/decision-bus",
    "/api/v106/paper-scorecard",
    "/api/v106/live-readiness-export",
    "/api/v106/connection-wizard",
    "/api/v106/log-health",
    "/api/v106/feature-audit",
    "/api/all-day/overnight-plan",
    "/api/crypto/why-not",
    "/api/intelligence/premarket/run",
    "/api/architecture/plan",
    "/api/paper-proof/refresh",
    "/api/pre-session/paper-checklist",
    "/api/v112/outcomes/refresh",
    "/api/v112/proof-report",
    "/api/v113/asi/refresh",
    "/api/v113/asi/report",
    "/api/learning/refresh",
    "/api/quantum-learning/refresh",
    "/api/agent/plan",
    "/api/warp/review",
    "/api/watchlist/refresh",
    "/api/system-review",
    "/api/live-data/snapshot",
    "/api/ops-dashboard",
    "/api/broker-reconciliation",
    "/api/order-origin-audit",
    "/api/live-readiness",
    "/api/decision-timeline",
    "/api/why-not",
    "/api/trade-replay",
    "/api/watchlist-lab",
    "/api/connections/refresh",
    "/api/tradingview/refresh-pine",
    "/api/tradingview/refresh-suite",
    "/api/receiving-accounts",
    "/api/receiving-accounts/delete",
    "/api/settings",
    "/api/live-master",
    "/api/owner-command",
    "/api/providers/setup",
    "/api/dashboard/layout",
    "/api/dashboard/button-audit",
    "/api/dashboard/button-event",
    "/api/trading-optimization/apply-paper-baseline",
    "/api/operations/readiness",
    "/api/crypto/watchlist/refresh",
    "/api/switchboard/preset",
    "/api/switchboard/audit",
    "/api/level5/review",
    "/api/executor/status",
    "/api/trade-plan/preview",
}

PUBLIC_POST_PATHS = {
    "/tradingview",
    "/api/payments/webhook/paypal",
    "/api/payments/webhook/plaid",
    "/api/subscription-leads",
    "/api/pmo-donations",
    "/api/pmo-investor-interest",
}


def harden_admin_paths(existing_paths: Iterable[str]) -> Set[str]:
    return set(existing_paths or set()) | PMO_V2055_EXTRA_ADMIN_POST_PATHS


def dependency_check(base_dir: Path | str = ".") -> Dict[str, Any]:
    base = Path(base_dir)
    modules = [
        "flask", "dotenv", "requests", "pmo_core", "pmo_core.agent", "pmo_core.storage",
        "pmo_core.v2055_hardening", "pmo_core.v206_manifest",
    ]
    optional = ["alpaca", "alpaca.trading.client", "alpaca.data.historical"]
    checks: List[Dict[str, Any]] = []
    for name in modules + optional:
        required = name not in optional
        checks.append({
            "name": name,
            "required": required,
            "ready": importlib.util.find_spec(name) is not None,
            "type": "python_module",
        })
    path_checks = [
        ("base_dir", base, True),
        ("pmo_core_dir", base / "pmo_core", True),
        ("settings_file", base / "pmo_settings.py", False),
        ("env_file", base / ".env", False),
    ]
    for name, path, required in path_checks:
        checks.append({"name": name, "required": required, "ready": Path(path).exists(), "type": "path", "path": str(path)})
    required_checks = [row for row in checks if row["required"]]
    ready_required = [row for row in required_checks if row["ready"]]
    ready_count = sum(1 for row in checks if row["ready"])
    return {
        "ok": len(ready_required) == len(required_checks),
        "ready_count": ready_count,
        "total_count": len(checks),
        "required_ready": len(ready_required),
        "required_total": len(required_checks),
        "checks": checks,
    }


def build_route_audit(app: Any, admin_paths: Iterable[str]) -> Dict[str, Any]:
    admin_paths = set(admin_paths or set())
    routes = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r.rule)):
        methods = sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"})
        if "POST" in methods and str(rule.rule) in PUBLIC_POST_PATHS:
            protection = "PUBLIC_WEBHOOK_OR_PUBLIC_INTAKE"
        elif "POST" in methods and str(rule.rule) in admin_paths:
            protection = "ADMIN_REQUIRED"
        elif "POST" in methods:
            protection = "POST_REVIEW_NEEDED"
        else:
            protection = "READ_ONLY_OR_PAGE"
        routes.append({
            "rule": str(rule.rule),
            "endpoint": str(rule.endpoint),
            "methods": methods,
            "protection": protection,
        })
    counts: Dict[str, int] = {}
    for row in routes:
        counts[row["protection"]] = counts.get(row["protection"], 0) + 1
    return {"ok": True, "route_count": len(routes), "counts": counts, "routes": routes}


def write_route_audit_file(app: Any, admin_paths: Iterable[str], output_path: Path | str) -> Dict[str, Any]:
    audit = build_route_audit(app, admin_paths)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    audit["file"] = str(path)
    return audit
