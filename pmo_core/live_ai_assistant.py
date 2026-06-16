"""PMO Desk Commander AI prompt and local answer builder."""
from __future__ import annotations

from typing import Any, Dict


PMO_DESK_COMMANDER_SYSTEM_PROMPT = """You are PMO Desk Commander AI.
You are allowed to inspect PMO Bot status, explain blockers, run read-only
reviews, and route safe admin-approved maintenance tools. You must never arm
live trading, submit live orders, bypass risk guards, expose secrets, or change
proof/live-readiness behavior without the backend admin/firewall approving the
exact tool call. Treat dashboard voice commands as convenience input, not as
trade authority."""


def build_local_ai_answer(command: Dict[str, Any], context: Dict[str, Any], result: Dict[str, Any] | None = None) -> Dict[str, Any]:
    tool = command.get("tool") or "chat"
    result = result or {}
    missing = context.get("missing") or []
    account = context.get("account") or {}
    readiness = context.get("live_readiness") or {}
    proof = context.get("paper_proof") or {}
    lines = [
        f"Command: {tool}.",
        f"Account equity: {account.get('equity', account.get('portfolio_value', 'unknown'))}.",
        f"Paper proof: {proof.get('proof_score', proof.get('score', 'unknown'))}.",
        f"Live readiness: {readiness.get('score', readiness.get('readiness_score', 'locked'))}.",
    ]
    if missing:
        lines.append("Missing: " + "; ".join(str(item) for item in missing[:5]))
    if result:
        status = result.get("status") or result.get("message") or ("complete" if result.get("ok") else "blocked")
        lines.append(f"Tool result: {status}.")
    lines.append("Live trading and direct order submission remain blocked from Desk Commander AI.")
    return {"ok": True, "answer": " ".join(lines), "provider": "local", "external_call": False}

