from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: Path, *, override: bool = False) -> set[str]:
    loaded: set[str] = set()
    if not path.exists():
        return loaded
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (override or key not in os.environ):
            os.environ[key] = value
            loaded.add(key)
    return loaded


BASE_DIR = Path(__file__).resolve().parents[1]
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)


def refresh_env_from_disk(*, override: bool = True) -> dict:
    loaded = load_dotenv(ENV_FILE, override=override)
    return {
        "ok": True,
        "env_file": str(ENV_FILE),
        "env_file_exists": ENV_FILE.exists(),
        "loaded_count": len(loaded),
        "provider_keys_loaded": {
            "openai": bool(os.getenv("OPENAI_API_KEY")),
            "claude": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")),
            "perplexity": bool(os.getenv("PERPLEXITY_API_KEY")),
            "gemini": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        },
    }


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def runtime_flags() -> dict:
    refresh_env_from_disk()
    return {
        "live_provider_calls": env_bool("PMOAI_LIVE_PROVIDER_CALLS", False),
        "cache_enabled": env_bool("PMOAI_CACHE_ENABLED", True),
    }


@dataclass(frozen=True)
class PMOAISettings:
    host: str = os.getenv("PMOAI_HOST", "0.0.0.0")
    port: int = int(os.getenv("PMOAI_PORT", "8093"))
    live_provider_calls: bool = env_bool("PMOAI_LIVE_PROVIDER_CALLS", False)
    cache_enabled: bool = env_bool("PMOAI_CACHE_ENABLED", True)
    monthly_budget_usd: float = float(os.getenv("PMOAI_MONTHLY_BUDGET_USD", "25"))
    db_path: Path = BASE_DIR / "pmo_storage.sqlite3"
    openai_model: str = os.getenv("PMOAI_OPENAI_MODEL", "gpt-4.1-mini")
    openai_coding_model: str = os.getenv("PMOAI_OPENAI_CODING_MODEL", "gpt-4.1")
    claude_model: str = os.getenv("PMOAI_CLAUDE_MODEL", "claude-sonnet-4-20250514")
    perplexity_model: str = os.getenv("PMOAI_PERPLEXITY_MODEL", "sonar")
    gemini_model: str = os.getenv("PMOAI_GEMINI_MODEL", "gemini-2.5-flash")


def provider_key_status() -> dict:
    refresh_env_from_disk()
    return {
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "claude": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")),
        "perplexity": bool(os.getenv("PERPLEXITY_API_KEY")),
        "gemini": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "local": True,
    }


def provider_key_details() -> dict:
    refresh_env_from_disk()
    return {
        "openai": {
            "configured": bool(os.getenv("OPENAI_API_KEY")),
            "required_env": "OPENAI_API_KEY",
            "setup_hint": "Add an official OpenAI API key to .env.",
        },
        "claude": {
            "configured": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")),
            "required_env": "ANTHROPIC_API_KEY or CLAUDE_API_KEY",
            "setup_hint": "Add an official Anthropic Claude API key to .env.",
        },
        "perplexity": {
            "configured": bool(os.getenv("PERPLEXITY_API_KEY")),
            "required_env": "PERPLEXITY_API_KEY",
            "setup_hint": "Add an official Perplexity API key to .env.",
        },
        "gemini": {
            "configured": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
            "required_env": "GEMINI_API_KEY or GOOGLE_API_KEY",
            "setup_hint": "Google OAuth client keys are not Gemini API keys; add a Gemini/Google AI API key to .env.",
        },
        "local": {
            "configured": True,
            "required_env": "none",
            "setup_hint": "Local planner works without paid provider keys.",
        },
    }


SETTINGS = PMOAISettings()
