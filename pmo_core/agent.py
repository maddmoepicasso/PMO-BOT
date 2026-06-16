from __future__ import annotations

import re
import time
from typing import Any, Dict, List


def build_agent_plan(goal: str, context: Dict[str, Any] | None = None, settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a safe PMO agent plan without enabling execution.

    This keeps PMO's AI planning layer separate from broker submission. The plan can
    recommend reviews, reports, or paper-only actions, but execution_allowed remains
    false unless the caller explicitly adds a separate verified execution layer.
    """
    context = context or {}
    settings = settings or {}
    goal_text = str(goal or "review PMO BOT state").strip()
    lowered = goal_text.lower()
    risk_terms = sorted(set(re.findall(r"\b(live|option|options|order|trade|alpaca|broker|real money|crypto|wire|payment|delete|keys?)\b", lowered)))
    live_switches_on = bool(settings.get("PMO_LIVE_TRADING_ENABLED")) or bool(settings.get("PMO_ALLOW_LIVE_TRADING"))
    automation_on = bool(settings.get("ORDER_AUTOMATION_ENABLED")) or bool(settings.get("ALPACA_ORDER_AUTOMATION"))
    dry_run = bool(settings.get("PMO_DRY_RUN_ORDERS", True))
    high_risk = bool(risk_terms) or live_switches_on or automation_on
    risk_level = "HIGH" if high_risk else "MEDIUM" if "review" in lowered or "optimize" in lowered else "LOW"
    steps: List[Dict[str, Any]] = [
        {"step": 1, "action": "Collect PMO status", "mode": "READ_ONLY"},
        {"step": 2, "action": "Check paper/dry-run/live switches", "mode": "SAFETY_REVIEW"},
        {"step": 3, "action": "Generate recommendation", "mode": "OWNER_REVIEW"},
    ]
    if high_risk:
        steps.append({"step": 4, "action": "Require owner confirmation before any state-changing action", "mode": "LOCKED"})
    return {
        "plan_id": f"PMO-AGENT-{int(time.time() * 1000)}",
        "goal": goal_text,
        "created_at": int(time.time()),
        "risk_level": risk_level,
        "mode": "PLAN_REVIEW_ONLY",
        "risk_terms": risk_terms,
        "owner_approval_required": True,
        "execution_allowed": False,
        "paper_mode": bool(context.get("paper_mode", settings.get("ALPACA_PAPER", True))),
        "dry_run": dry_run,
        "live_master": live_switches_on,
        "order_automation": automation_on,
        "steps": steps,
        "safe_note": "Agent planning never bypasses PMO execution gates or admin approval.",
    }
