"""Read-only PMO code reviewer for Desk Commander AI."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SECRET_RE = re.compile(r"(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE)


def redact_secrets(text: str) -> str:
    return SECRET_RE.sub(lambda match: match.group(1) + "='***REDACTED***'", text)


def _safe_candidate(root: Path, value: str) -> Optional[Path]:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root.resolve(strict=False))
    except Exception:
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    allowed = {".py", ".html", ".js", ".json", ".md", ".txt"}
    if resolved.suffix.lower() not in allowed:
        return None
    return resolved


def review_code(root: Path, files: Optional[Iterable[str]] = None, max_chars_per_file: int = 180_000) -> Dict[str, Any]:
    root = root.resolve(strict=False)
    requested = list(files or ["pmo_bot.py", "pmo_settings.py"])
    safe_files = []
    for value in requested[:8]:
        candidate = _safe_candidate(root, str(value))
        if candidate:
            safe_files.append(candidate)

    findings: List[Dict[str, Any]] = []
    file_summaries: List[Dict[str, Any]] = []
    for path in safe_files:
        text = path.read_text(encoding="utf-8", errors="replace")[:max_chars_per_file]
        redacted = redact_secrets(text)
        lower = redacted.lower()
        route_count = redacted.count("@app.route(")
        if "pmo_allow_live_trading" in lower and "pmo_live_trading_enabled" in lower:
            findings.append({"severity": "INFO", "file": str(path), "message": "Live trading appears gated by explicit PMO live settings."})
        if "pmo_require_admin" in lower:
            findings.append({"severity": "INFO", "file": str(path), "message": "Admin token protection is present in this file."})
        if route_count > 150:
            findings.append({"severity": "WARN", "file": str(path), "message": f"Large Flask surface detected: {route_count} routes. Keep new features modular."})
        if SECRET_RE.search(text):
            findings.append({"severity": "WARN", "file": str(path), "message": "Potential secret-like assignment found and redacted in review output."})
        file_summaries.append({
            "file": str(path),
            "chars_reviewed": len(redacted),
            "route_count": route_count,
            "contains_admin_gate": "pmo_require_admin" in lower,
            "contains_live_gate": "pmo_allow_live_trading" in lower or "pmo_live_trading_enabled" in lower,
        })

    patch_plan = [
        "Keep AI assistant tools routed through a safety firewall.",
        "Require admin token for write-capable tools.",
        "Keep live trading and order submission blocked from voice/chat commands.",
        "Prefer modular pmo_core files over expanding pmo_bot.py further.",
    ]
    test_plan = [
        "python -m py_compile pmo_bot.py pmo_settings.py",
        "python -m unittest discover -s tests",
        "GET /api/ai/status",
        "POST /api/ai/command with unsafe live text should return blocked=true",
    ]
    return {
        "ok": True,
        "mode": "READ_ONLY_CODE_REVIEW",
        "files": file_summaries,
        "findings": findings,
        "patch_plan": patch_plan,
        "test_plan": test_plan,
        "secret_redaction": "enabled",
    }

