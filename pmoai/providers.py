from __future__ import annotations

import os
import time
from typing import Any

import requests

from .config import SETTINGS, provider_key_status, runtime_flags
from .records import diagnose_records, diagnostic_text


SYSTEM_PROMPT = """You are PMOAI, a professional project management AI assistant and compliant multi-provider router.
Help with project plans, timelines, SOPs, automation, reports, research, coding tasks, business workflows,
meeting summaries, team coordination, document analysis, and decision support.
Use only official APIs, approved user keys, authorized accounts, lawful caching, and permitted data sources.
Never bypass billing, authentication, provider terms, rate limits, licensing, or access controls.
Protect secrets and private data. Give practical answers and mention provider/source use when useful.
When users cannot see closed threads, closed trades, completed tasks, archived conversations, or historical records,
do not assume the system is broken. Start with: "Nothing is necessarily wrong. Closed records are often hidden by
filters, permissions, date range, or sync settings. I'll check whether we are pulling active-only data or full
historical data." Then check data source, historical sync scope, permissions, date filters, active-only dashboard
views, live-only API pulls, vector-memory indexing, workspace/account/environment selection, deleted/expired records,
and whether a manual refresh, re-sync, or permission update is needed."""


def provider_model(provider: str, model_role: str) -> str:
    if provider == "openai" and model_role == "coding":
        return SETTINGS.openai_coding_model
    if provider == "openai":
        return SETTINGS.openai_model
    if provider == "claude":
        return SETTINGS.claude_model
    if provider == "perplexity":
        return SETTINGS.perplexity_model
    if provider == "gemini":
        return SETTINGS.gemini_model
    return "local-planner"


def local_answer(message: str, route: dict[str, Any]) -> dict[str, Any]:
    if route.get("task_type") in {"historical_records", "open_records"}:
        diagnostic = diagnose_records("all", include_deleted=True)
        return {
            "answer": diagnostic_text(diagnostic),
            "citations": [],
            "mode": "records_diagnostic",
            "diagnostic": diagnostic,
        }
    return {
        "answer": (
            "PMOAI routed this request to local planning mode. "
            "Live provider calls are disabled until PMOAI_LIVE_PROVIDER_CALLS=true and the selected provider key is configured.\n\n"
            f"Recommended provider: {route['provider']} ({route['model_role']}).\n"
            f"Reason: {route['reason']}\n\n"
            "Next action: add the provider API key in .env, refresh PMOAI status, then turn on live provider calls when you are ready to spend API credits."
        ),
        "citations": [],
        "mode": "local_planner",
    }


def call_provider(message: str, route: dict[str, Any]) -> tuple[dict[str, Any], int, str]:
    provider = route["provider"]
    model = provider_model(provider, route.get("model_role", "general"))
    keys = provider_key_status()
    flags = runtime_flags()
    if provider == "local" or not flags["live_provider_calls"] or not keys.get(provider):
        return local_answer(message, route), 0, "local-planner"
    started = time.perf_counter()
    if provider == "openai":
        response = call_openai(message, model)
    elif provider == "claude":
        response = call_claude(message, model)
    elif provider == "perplexity":
        response = call_perplexity(message, model)
    elif provider == "gemini":
        response = call_gemini(message, model)
    else:
        response = local_answer(message, route)
    latency = int((time.perf_counter() - started) * 1000)
    return response, latency, model


def call_openai(message: str, model: str) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "")
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
    }
    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    data = r.json()
    if r.status_code >= 300:
        raise RuntimeError(data.get("error", {}).get("message", f"OpenAI HTTP {r.status_code}"))
    text = data.get("output_text") or ""
    if not text:
        parts = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"}:
                    parts.append(content.get("text", ""))
        text = "\n".join(parts).strip()
    return {"answer": text, "citations": [], "raw_provider": "openai"}


def call_claude(message: str, model: str) -> dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY", "")
    payload = {
        "model": model,
        "max_tokens": 1600,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": message}],
    }
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    data = r.json()
    if r.status_code >= 300:
        raise RuntimeError(data.get("error", {}).get("message", f"Claude HTTP {r.status_code}"))
    text = "\n".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
    return {"answer": text, "citations": [], "raw_provider": "claude"}


def call_perplexity(message: str, model: str) -> dict[str, Any]:
    api_key = os.getenv("PERPLEXITY_API_KEY", "")
    payload = {"model": model, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": message}]}
    r = requests.post(
        "https://api.perplexity.ai/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    data = r.json()
    if r.status_code >= 300:
        raise RuntimeError(data.get("error", {}).get("message", f"Perplexity HTTP {r.status_code}"))
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return {"answer": text, "citations": data.get("citations", []), "raw_provider": "perplexity"}


def call_gemini(message: str, model: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": message}]}],
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    r = requests.post(url, json=payload, timeout=60)
    data = r.json()
    if r.status_code >= 300:
        raise RuntimeError(data.get("error", {}).get("message", f"Gemini HTTP {r.status_code}"))
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    text = "\n".join(part.get("text", "") for part in parts)
    return {"answer": text, "citations": [], "raw_provider": "gemini"}
