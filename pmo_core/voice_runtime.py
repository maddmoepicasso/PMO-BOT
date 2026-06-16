"""Voice runtime status for PMO Desk Commander AI."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


def voice_runtime_status(settings: Optional[Dict[str, Any]] = None, origin: str = "") -> Dict[str, Any]:
    settings = settings or {}
    realtime_enabled = bool(settings.get("PMO_AI_REALTIME_ENABLED", False))
    openai_ready = bool(os.getenv("OPENAI_API_KEY", "").strip())
    return {
        "enabled": bool(settings.get("ENABLE_PMO_LIVE_AI_ASSISTANT", True)),
        "mode": settings.get("PMO_LIVE_AI_MODE", "DESK_COPILOT"),
        "browser_speech_supported": True,
        "web_speech_fallback": bool(settings.get("PMO_AI_BROWSER_SPEECH_FALLBACK", True)),
        "push_to_talk_required": bool(settings.get("PMO_AI_REQUIRE_PUSH_TO_TALK", True)),
        "realtime_enabled": realtime_enabled,
        "realtime_configured": realtime_enabled and openai_ready,
        "voice_provider": settings.get("PMO_AI_VOICE_PROVIDER", "browser_speech"),
        "origin": origin,
        "safety_note": "Voice can inspect and explain PMO. Voice cannot arm live trading or submit orders.",
    }

