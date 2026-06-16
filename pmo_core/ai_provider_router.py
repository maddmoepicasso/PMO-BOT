"""Provider status and local fallback responses for PMO Desk Commander AI."""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


def _env_ready(*names: str) -> bool:
    return any(bool(os.getenv(name, "").strip()) for name in names)


def provider_status(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    settings = settings or {}
    live_calls = bool(settings.get("PMO_LIVE_AI_ALLOW_EXTERNAL_PROVIDER_CALLS", False))
    return {
        "live_calls_enabled": live_calls,
        "default_provider": settings.get("PMO_AI_DEFAULT_PROVIDER", "local"),
        "reasoning_provider": settings.get("PMO_AI_REASONING_PROVIDER", settings.get("PMO_AI_DEFAULT_PROVIDER", "local")),
        "voice_provider": settings.get("PMO_AI_VOICE_PROVIDER", "browser_speech"),
        "providers": {
            "openai": {"configured": _env_ready("OPENAI_API_KEY"), "live_calls": live_calls},
            "claude": {"configured": _env_ready("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "PMO_ANTHROPIC_API_KEY"), "live_calls": live_calls},
            "gemini": {"configured": _env_ready("GEMINI_API_KEY", "GOOGLE_API_KEY"), "live_calls": live_calls},
            "local": {"configured": True, "live_calls": True},
        },
        "safety_note": "Provider status never returns secrets. External calls are off unless explicitly enabled in settings.",
    }


def summarize_ai_response(text: str, max_chars: int = 900) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3].rstrip() + "..."


def ask_ai(prompt: str, context: Optional[Dict[str, Any]] = None, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Local safe fallback. Does not call external providers by default."""
    context = context or {}
    settings = settings or {}
    readiness = context.get("live_readiness") or {}
    proof = context.get("paper_proof") or {}
    missing = context.get("missing") or []
    answer = [
        "PMO Desk Commander is running in local safe mode.",
        f"Mode: {context.get('bot_mode', settings.get('BOT_MODE', 'UNKNOWN'))}.",
        f"Live readiness: {readiness.get('score', readiness.get('readiness_score', 'unknown'))}.",
        f"Paper proof: {proof.get('proof_score', proof.get('score', 'unknown'))}.",
    ]
    if missing:
        answer.append("Main blockers: " + "; ".join(str(item) for item in missing[:5]))
    answer.append("Live trading and order submission are blocked from AI commands.")
    return {
        "ok": True,
        "provider": "local",
        "external_call": False,
        "answer": summarize_ai_response(" ".join(answer)),
        "prompt_summary": summarize_ai_response(prompt, 300),
    }


def ask_second_opinion(prompt: str, context: Optional[Dict[str, Any]] = None, settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = ask_ai(prompt, context=context, settings=settings)
    base["answer"] = (
        "Second opinion: keep PMO in paper-safe proof-building mode, inspect closed-trade quality, "
        "and do not let AI approval override score, risk, broker, PDT, or proof gates."
    )
    base["provider"] = "local_second_opinion"
    return base


def stream_ai_response(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return ask_ai(*args, **kwargs)

