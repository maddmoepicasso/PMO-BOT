"""Dashboard metadata for PMO Desk Commander AI."""
from __future__ import annotations

from typing import Dict, List


DESK_COMMANDER_PANEL = {
    "id": "panelDeskCommanderAI",
    "title": "PMO Desk Commander AI",
    "mode": "DESK_COPILOT",
    "safety": "NO_LIVE_TRADES_BY_AI",
}


def desk_commander_command_chips() -> List[Dict[str, str]]:
    return [
        {"label": "Status", "command": "status"},
        {"label": "What Is Missing", "command": "what is missing"},
        {"label": "Readiness", "command": "live readiness"},
        {"label": "Checklist", "command": "run pre-session checklist"},
        {"label": "Sync Journal", "command": "sync journal"},
        {"label": "Refresh Connections", "command": "refresh connections"},
        {"label": "Backtest", "command": "run backtest"},
        {"label": "Firewall", "command": "run firewall check"},
        {"label": "Code Review", "command": "code review"},
    ]

