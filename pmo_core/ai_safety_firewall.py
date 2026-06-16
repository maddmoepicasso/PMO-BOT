"""Safety firewall for PMO Desk Commander AI commands."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from .ai_tool_registry import (
    ADMIN_REQUIRED,
    BLOCKED,
    DEFAULT_BLOCKED_COMMANDS,
    FRONTEND_ONLY,
    READ_ONLY,
    build_tool_manifest,
    find_tool,
)


DANGEROUS_TEXT_PATTERNS = [
    r"\b(go live|unlock live|arm live|live master|pmO go live)\b",
    r"\b(place|submit|send|execute)\b.*\b(order|trade)\b",
    r"\b(approve)\b.*\b(trade|order)\b",
    r"\b(disable|turn off|bypass)\b.*\b(risk|guard|firewall|breaker|proof|pdt)\b",
    r"\b(secret|api key|password|private key|token)\b.*\b(show|print|reveal|export)\b",
    r"\b(delete|wipe|drop)\b.*\b(journal|trade|data|database|logs)\b",
]


def _settings_list(settings: Dict[str, Any], name: str, fallback: Iterable[str]) -> List[str]:
    value = settings.get(name)
    if isinstance(value, list):
        return [str(item).strip().lower() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip().lower() for item in value.split(",") if item.strip()]
    return [str(item).strip().lower() for item in fallback]


def _contains_dangerous_text(payload: Dict[str, Any]) -> Optional[str]:
    text = " ".join(str(payload.get(key, "")) for key in ("text", "command", "prompt", "notes", "message"))
    for pattern in DANGEROUS_TEXT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def validate_ai_tool_call(
    tool_name: str,
    payload: Optional[Dict[str, Any]] = None,
    user_context: Optional[Dict[str, Any]] = None,
    settings: Optional[Dict[str, Any]] = None,
    manifest: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload = payload or {}
    user_context = user_context or {}
    settings = settings or {}
    manifest = manifest or build_tool_manifest()
    clean_tool = str(tool_name or "").strip().lower()
    tool = find_tool(clean_tool, manifest)
    blocked_commands = _settings_list(settings, "PMO_AI_BLOCKED_COMMANDS", DEFAULT_BLOCKED_COMMANDS)
    allowed_commands = _settings_list(settings, "PMO_AI_ALLOWED_COMMANDS", [row.get("name", "") for row in manifest])

    if not clean_tool:
        return {"ok": False, "blocked": True, "reason": "Missing AI tool name.", "severity": "WARN"}
    if clean_tool in blocked_commands:
        return {"ok": False, "blocked": True, "reason": f"{clean_tool} is blocked by PMO AI policy.", "severity": "CRITICAL"}
    if clean_tool not in allowed_commands:
        return {"ok": False, "blocked": True, "reason": f"{clean_tool} is not in PMO_AI_ALLOWED_COMMANDS.", "severity": "WARN"}
    if not tool:
        return {"ok": False, "blocked": True, "reason": f"{clean_tool} is not registered in the AI tool manifest.", "severity": "WARN"}
    if tool.get("permission") == BLOCKED:
        return {"ok": False, "blocked": True, "reason": "Tool is explicitly blocked.", "severity": "CRITICAL", "tool": tool}

    dangerous_pattern = _contains_dangerous_text(payload)
    if dangerous_pattern:
        return {
            "ok": False,
            "blocked": True,
            "reason": "Command text matches a blocked live/order/secrets/destructive pattern.",
            "severity": "CRITICAL",
            "pattern": dangerous_pattern,
            "tool": tool,
        }

    input_type = str(user_context.get("input_type") or payload.get("input_type") or "text").lower()
    if input_type == "voice" and not bool(tool.get("voice_allowed", True)):
        return {"ok": False, "blocked": True, "reason": "This tool is not allowed from voice input.", "severity": "WARN", "tool": tool}

    if bool(tool.get("live_order_allowed", False)) or "live" in clean_tool:
        return {"ok": False, "blocked": True, "reason": "Desk Commander cannot arm live trading or create live orders.", "severity": "CRITICAL", "tool": tool}
    if bool(tool.get("paper_order_allowed", False)):
        return {"ok": False, "blocked": True, "reason": "Desk Commander cannot submit paper orders directly.", "severity": "CRITICAL", "tool": tool}

    permission = str(tool.get("permission") or READ_ONLY)
    admin_unlocked = bool(user_context.get("admin_unlocked"))
    if input_type == "voice" and permission == ADMIN_REQUIRED and not bool(settings.get("PMO_AI_ALLOW_SETTING_CHANGES_BY_VOICE", False)):
        return {"ok": False, "blocked": True, "reason": "Voice cannot run admin/write tools.", "severity": "WARN", "tool": tool}
    if permission == ADMIN_REQUIRED and not admin_unlocked:
        return {"ok": False, "blocked": True, "reason": "Admin token required for this PMO AI tool.", "severity": "WARN", "tool": tool, "admin_required": True}

    return {
        "ok": True,
        "blocked": False,
        "reason": "Allowed by PMO Desk Commander firewall.",
        "severity": "INFO",
        "tool": tool,
        "permission": permission,
        "frontend_only": permission == FRONTEND_ONLY,
    }

