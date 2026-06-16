from __future__ import annotations

from dataclasses import dataclass

from .records import is_historical_records_request, is_open_records_request


@dataclass(frozen=True)
class RouteDecision:
    task_type: str
    provider: str
    model_role: str
    fallbacks: list[str]
    reason: str
    needs_sources: bool = False
    needs_repo: bool = False
    sensitivity: str = "medium"

    def to_dict(self) -> dict:
        return {
            "task_type": self.task_type,
            "provider": self.provider,
            "model_role": self.model_role,
            "fallbacks": self.fallbacks,
            "reason": self.reason,
            "needs_sources": self.needs_sources,
            "needs_repo": self.needs_repo,
            "sensitivity": self.sensitivity,
        }


def choose_route(message: str, force_provider: str | None = None) -> RouteDecision:
    text = message.lower()
    if force_provider:
        return RouteDecision("manual", force_provider, force_provider, ["local"], "User forced provider selection.")
    if is_historical_records_request(message):
        return RouteDecision(
            "historical_records",
            "local",
            "records_diagnostic",
            ["openai", "claude"],
            "User is asking about closed, archived, completed, unavailable, or historical records.",
            False,
            False,
            "high",
        )
    if is_open_records_request(message):
        return RouteDecision(
            "open_records",
            "local",
            "records_diagnostic",
            ["openai"],
            "User is asking about active/open record visibility.",
        )
    if any(word in text for word in ["latest", "current", "today", "news", "sources", "citation", "research", "web search"]):
        return RouteDecision("research", "perplexity", "web_research", ["openai", "gemini", "local"], "Request needs current/source-backed information.", True)
    if any(word in text for word in ["code", "coding", "software", "bug", "repo", "repository", "script", "debug", "function", "api", "database", "frontend", "backend"]):
        return RouteDecision("coding", "openai", "coding", ["claude", "local"], "Request is software/coding oriented.", False, True)
    if any(word in text for word in ["pdf", "document", "contract", "long", "transcript", "analyze this file", "summarize document"]):
        return RouteDecision("document_analysis", "claude", "long_context", ["openai", "gemini", "local"], "Request likely benefits from long-context analysis.")
    if any(word in text for word in ["image", "screenshot", "video", "audio", "google drive", "gmail", "sheets", "docs"]):
        return RouteDecision("multimodal_google", "gemini", "multimodal", ["openai", "local"], "Request mentions multimodal or Google ecosystem work.")
    if len(message) < 220 and any(word in text for word in ["rename", "title", "short", "simple", "quick", "format"]):
        return RouteDecision("simple", "local", "local", ["openai"], "Simple request can be handled locally or from cache.")
    return RouteDecision("general", "openai", "general", ["claude", "gemini", "local"], "General assistant request.")
