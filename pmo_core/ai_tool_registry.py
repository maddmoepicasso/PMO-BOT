"""PMO Desk Commander AI tool registry.

The registry describes what the assistant may ask PMO Bot to do. It is not an
executor. Every write-capable tool still has to pass the backend firewall.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


READ_ONLY = "READ_ONLY"
FRONTEND_ONLY = "FRONTEND_ONLY"
ADMIN_REQUIRED = "ADMIN_REQUIRED"
BLOCKED = "BLOCKED"


DEFAULT_ALLOWED_COMMANDS = [
    "get_pmo_status",
    "get_live_readiness",
    "get_safety_status",
    "refresh_connections",
    "run_switchboard_audit",
    "run_paper_proof",
    "refresh_watchlist",
    "run_backtest",
    "run_cobr_sim",
    "run_firewall_check",
    "run_pre_session_checklist",
    "explain_what_is_missing",
    "open_dashboard_section",
    "sync_journal",
    "apply_paper_safe_baseline",
    "enable_paper_executor_collection",
    "return_crypto_research_only",
    "review_code",
    "make_patch_plan",
    "stop_voice",
]


DEFAULT_BLOCKED_COMMANDS = [
    "enable_live_trading",
    "arm_live_master",
    "place_live_order",
    "place_order",
    "approve_trade",
    "approve_paper_trade",
    "disable_risk_guard",
    "disable_day_loss_guard",
    "show_secret",
    "export_secret",
    "delete_data",
]


def _tool(
    name: str,
    label: str,
    permission: str = READ_ONLY,
    description: str = "",
    endpoint: str = "",
    method: str = "POST",
    frontend_action: str = "",
    live_order_allowed: bool = False,
    paper_order_allowed: bool = False,
    owner_confirm_required: bool = False,
    voice_allowed: bool = True,
) -> Dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "permission": permission,
        "description": description,
        "endpoint": endpoint,
        "method": method,
        "frontend_action": frontend_action,
        "live_order_allowed": live_order_allowed,
        "paper_order_allowed": paper_order_allowed,
        "owner_confirm_required": owner_confirm_required,
        "voice_allowed": voice_allowed,
    }


def build_tool_manifest() -> List[Dict[str, Any]]:
    """Return the Desk Commander tool manifest."""
    return [
        _tool("get_pmo_status", "PMO Status", READ_ONLY, "Read bot health, account, regime, and proof state.", "/api/status", "GET"),
        _tool("get_live_readiness", "Live Readiness", READ_ONLY, "Explain why live readiness is locked or unlocked.", "/api/live-readiness"),
        _tool("get_safety_status", "Safety Status", READ_ONLY, "Read current PMO safety mode and proof snapshot.", "/api/safety/status", "GET"),
        _tool("refresh_connections", "Refresh Connections", READ_ONLY, "Refresh broker and service connection status.", "/api/connections/refresh"),
        _tool("run_switchboard_audit", "Switchboard Audit", READ_ONLY, "Audit settings without changing them.", "/api/switchboard/audit"),
        _tool("run_paper_proof", "Paper Proof", READ_ONLY, "Refresh/read paper proof and v112 proof data.", "/api/paper-proof/refresh"),
        _tool("refresh_watchlist", "Refresh Watchlist", READ_ONLY, "Refresh auto-watchlist in read/report mode.", "/api/watchlist/auto-refresh"),
        _tool("run_backtest", "Run Backtest", READ_ONLY, "Run the research-only backtest simulator.", "/api/backtest/run"),
        _tool("run_cobr_sim", "Run COBR Sim", READ_ONLY, "Run the research-only COBR simulator.", "/api/cobr/simulate"),
        _tool("run_firewall_check", "Firewall Check", READ_ONLY, "Read the execution firewall state.", "/api/firewall/status"),
        _tool("run_pre_session_checklist", "Pre-Session Checklist", READ_ONLY, "Run the paper-safe pre-session checklist.", "/api/pre-session/paper-checklist"),
        _tool("explain_what_is_missing", "What Is Missing", READ_ONLY, "Summarize blockers, proof gaps, and next steps."),
        _tool("open_dashboard_section", "Open Dashboard Section", FRONTEND_ONLY, "Ask the dashboard to scroll to a PMO section.", frontend_action="scroll"),
        _tool("stop_voice", "Stop Voice", FRONTEND_ONLY, "Stop browser voice capture/speech.", frontend_action="stop_voice"),
        _tool("sync_journal", "Sync Journal", ADMIN_REQUIRED, "Sync broker paper fills and optionally close paper target/stop hits.", "/api/trade-journal/sync", owner_confirm_required=True),
        _tool("apply_paper_safe_baseline", "Apply Paper Safe", ADMIN_REQUIRED, "Apply PMO PAPER SAFE baseline only.", "/api/safety/paper-safe", owner_confirm_required=True),
        _tool("enable_paper_executor_collection", "Enable Paper Executor", ADMIN_REQUIRED, "Enable paper-only executor collection mode.", "/api/safety/stock-paper-executor", owner_confirm_required=True),
        _tool("return_crypto_research_only", "Crypto Research Only", ADMIN_REQUIRED, "Return crypto to research-only mode.", "/api/crypto/research-only", owner_confirm_required=True),
        _tool("review_code", "Code Review", ADMIN_REQUIRED, "Run local read-only PMO code review.", "/api/ai/code-review", owner_confirm_required=True, voice_allowed=False),
        _tool("make_patch_plan", "Patch Plan", ADMIN_REQUIRED, "Create a local patch plan without editing files.", "/api/ai/code-review", owner_confirm_required=True, voice_allowed=False),
    ]


def build_blocked_manifest() -> List[Dict[str, Any]]:
    return [
        _tool(name, name.replace("_", " ").title(), BLOCKED, "Blocked by PMO Desk Commander firewall.", voice_allowed=False)
        for name in DEFAULT_BLOCKED_COMMANDS
    ]


def find_tool(name: str, manifest: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    clean = str(name or "").strip().lower()
    for tool in manifest or build_tool_manifest():
        if str(tool.get("name", "")).lower() == clean:
            return tool
    return None

