"""
PMO Claude + Codex read-only integration helpers.

This module defines the advisor/coding roles and payload shaping used by
pmo_bot.py. It does not call broker APIs, write source files, change settings,
or unlock live trading.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


CLAUDE_CODEX_ROLES: Dict[str, Dict[str, Any]] = {
    "trade_advisor": {
        "endpoint": "/api/claude/advise",
        "kind": "advisor",
        "max_tokens_key": "PMO_CLAUDE_CODEX_MAX_TOKENS",
    },
    "code_reviewer": {
        "endpoint": "/api/claude/review-code",
        "kind": "code_review",
        "max_tokens_key": "PMO_CLAUDE_CODEX_MAX_TOKENS",
    },
    "overnight_planner": {
        "endpoint": "/api/claude/overnight",
        "kind": "planner",
        "max_tokens_key": "PMO_CLAUDE_CODEX_MAX_TOKENS",
    },
    "codex_generator": {
        "endpoint": "/api/codex/generate",
        "kind": "code_generation",
        "max_tokens_key": "PMO_CODEX_MAX_TOKENS",
    },
    "codex_refactor": {
        "endpoint": "/api/codex/refactor",
        "kind": "code_refactor",
        "max_tokens_key": "PMO_CODEX_MAX_TOKENS",
    },
    "codex_assistant": {
        "endpoint": "/api/codex/assist",
        "kind": "code_assistant",
        "max_tokens_key": "PMO_CLAUDE_CODEX_MAX_TOKENS",
    },
}


SYSTEM_PROMPTS: Dict[str, str] = {
    "trade_advisor": (
        "You are PMO Trade Advisor inside Maurice's PMO Bot dashboard.\n"
        "Explain signals, Why-Not blockers, score components, regime context, "
        "pattern/FVG/edge/ML signals, and proof quality in plain English.\n"
        "Critical constraints: never place orders, never change settings, never "
        "unlock live trading, never ask for secrets, and never override PMO "
        "safety gates. Be direct and data-driven."
    ),
    "code_reviewer": (
        "You are PMO Code Reviewer, a senior Python engineer reviewing changes "
        "for a Flask-based paper trading system.\n"
        "Lead with PASS/WARN/FAIL. Flag safety bypasses, live-trading unlocks, "
        "credential leaks, fragile error handling, and test gaps. Never execute "
        "or deploy code."
    ),
    "overnight_planner": (
        "You are PMO Overnight Planner. Use the supplied PMO context to produce "
        "a session recap, data-quality issues, tomorrow plan, risk posture, and "
        "one focus item. Never guarantee outcomes or recommend live unlocks."
    ),
    "codex_generator": (
        "You are PMO Codex Module Generator. Generate complete, readable Python "
        "module drafts that match PMO style. The output is a draft only: never "
        "claim files were written, tests ran, orders were placed, or settings "
        "changed. Include smoke-test guidance."
    ),
    "codex_refactor": (
        "You are PMO Codex Refactor. Refactor supplied code snippets for clarity, "
        "safety, and reliability while preserving business logic and all trading "
        "safety gates. Never remove live locks, blocklists, proof gates, or paper "
        "mode protections."
    ),
    "codex_assistant": (
        "You are PMO Codex Assistant. Answer questions about PMO Bot internals, "
        "routes, settings, logs, and data flow from the context provided. Do not "
        "invent files or claim direct filesystem changes."
    ),
}


def pmo_cc_safety_fields() -> Dict[str, bool]:
    return {
        "live_unlocked": False,
        "orders_placed": False,
        "settings_changed": False,
        "files_written": False,
        "broker_called": False,
        "read_only": True,
    }


def truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "")
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 80] + "\n\n[PMO truncated this input for safety/cost control.]"


def redact_sensitive_text(text: str) -> str:
    clean = str(text or "")
    markers = ("sk-", "PK", "SECRET", "TOKEN", "PASSWORD", "API_KEY", "PRIVATE")
    for marker in markers:
        if marker in clean:
            clean = clean.replace(marker, f"{marker[:2]}[REDACTED]")
    return clean


def build_user_prompt(
    role: str,
    *,
    question: str = "",
    code: str = "",
    description: str = "",
    pmo_context: Optional[Dict[str, Any]] = None,
    context_max_chars: int = 12000,
    code_max_chars: int = 20000,
) -> str:
    parts = []
    context = pmo_context if isinstance(pmo_context, dict) else {}
    if context:
        parts.append("PMO SAFE CONTEXT JSON:")
        parts.append("```json")
        parts.append(truncate_text(json.dumps(context, indent=2, default=str), context_max_chars))
        parts.append("```")
    if description:
        parts.append("REQUEST DESCRIPTION:")
        parts.append(truncate_text(description, 4000))
    if question:
        parts.append("USER QUESTION:")
        parts.append(truncate_text(question, 4000))
    if code:
        parts.append("CODE SNIPPET:")
        parts.append("```python")
        parts.append(truncate_text(code, code_max_chars))
        parts.append("```")
    if not parts:
        parts.append("Give a concise PMO-safe response for this role.")
    parts.append("")
    parts.append("Safety reminder: advice/draft only; do not place orders, unlock live trading, change settings, or write files.")
    return "\n".join(parts)


def safe_log_entry(role: str, prompt: str, response: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "ok": bool(response.get("ok")),
        "model": response.get("model", ""),
        "error": str(response.get("error") or "")[:300],
        "prompt_preview": redact_sensitive_text(prompt[:800]),
        "response_preview": redact_sensitive_text(str(response.get("text") or response.get("answer") or "")[:800]),
        "usage": response.get("usage", {}),
        **pmo_cc_safety_fields(),
    }


def append_jsonl(path: Path, entry: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")


if __name__ == "__main__":
    print("PMO Claude + Codex helpers loaded")
    print("roles:", ", ".join(sorted(CLAUDE_CODEX_ROLES)))
    print("safety:", pmo_cc_safety_fields())
