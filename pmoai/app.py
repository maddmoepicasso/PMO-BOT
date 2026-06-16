from __future__ import annotations

import time
from typing import Any

from flask import Flask, jsonify, request

from .config import SETTINGS, provider_key_details, provider_key_status, refresh_env_from_disk, runtime_flags
from .providers import call_provider, provider_model
from .records import CHECKLIST, DEFAULT_RESPONSE, diagnose_records
from .router import choose_route
from .storage import PMOAIStore


app = Flask(__name__)
store = PMOAIStore(SETTINGS.db_path)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-PMOAI-User"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/api/pmoai/health", methods=["GET", "OPTIONS"])
def health():
    if request.method == "OPTIONS":
        return ("", 204)
    flags = runtime_flags()
    return jsonify({
        "ok": True,
        "service": "PMOAI",
        "version": "0.1.0",
        "live_provider_calls": flags["live_provider_calls"],
        "cache_enabled": flags["cache_enabled"],
        "providers": provider_key_status(),
    })


@app.route("/api/pmoai/env/reload", methods=["POST", "OPTIONS"])
def reload_env():
    if request.method == "OPTIONS":
        return ("", 204)
    status = refresh_env_from_disk()
    return jsonify(status)


@app.route("/api/pmoai/providers", methods=["GET", "OPTIONS"])
def providers():
    if request.method == "OPTIONS":
        return ("", 204)
    keys = provider_key_status()
    details = provider_key_details()
    flags = runtime_flags()
    rows = []
    for provider in ["openai", "claude", "perplexity", "gemini", "local"]:
        detail = details.get(provider, {})
        rows.append({
            "provider": provider,
            "configured": keys.get(provider, False),
            "model": provider_model(provider, "general"),
            "live_enabled": flags["live_provider_calls"] and keys.get(provider, False),
            "required_env": detail.get("required_env", ""),
            "setup_hint": detail.get("setup_hint", ""),
        })
    return jsonify({"ok": True, "providers": rows})


@app.route("/api/pmoai/route", methods=["POST", "OPTIONS"])
def route_only():
    if request.method == "OPTIONS":
        return ("", 204)
    payload = request.get_json(force=True, silent=True) or {}
    message = str(payload.get("message", "")).strip()
    force_provider = payload.get("provider")
    if not message:
        return jsonify({"ok": False, "message": "message is required"}), 400
    decision = choose_route(message, force_provider).to_dict()
    return jsonify({"ok": True, "route": decision})


@app.route("/api/pmoai/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return ("", 204)
    payload: dict[str, Any] = request.get_json(force=True, silent=True) or {}
    message = str(payload.get("message", "")).strip()
    force_provider = payload.get("provider")
    actor = request.headers.get("X-PMOAI-User", "dashboard")
    if not message:
        return jsonify({"ok": False, "message": "message is required"}), 400
    decision = choose_route(message, force_provider).to_dict()
    cache_key = store.cache_key(message, decision)
    flags = runtime_flags()
    if flags["cache_enabled"] and not payload.get("no_cache"):
        cached = store.get_cache(cache_key)
        if cached:
            store.log_audit("cache_hit", actor, cached["provider"], decision["task_type"])
            return jsonify({"ok": True, "cached": True, "route": decision, **cached["response"]})
    started = time.perf_counter()
    try:
        response, latency_ms, model = call_provider(message, decision)
        if not latency_ms:
            latency_ms = int((time.perf_counter() - started) * 1000)
        routed_provider = decision["provider"]
        provider = "local" if response.get("mode") == "local_planner" else routed_provider
        store.log_usage(provider, model, decision["task_type"], "ok", latency_ms, f"routed={routed_provider}")
        store.log_audit("chat", actor, provider, decision["reason"])
        result = {
            "answer": response.get("answer", ""),
            "citations": response.get("citations", []),
            "provider": provider,
            "model": model,
            "latency_ms": latency_ms,
            "live_provider_call": provider == routed_provider and flags["live_provider_calls"] and provider_key_status().get(provider, False),
        }
        if response.get("diagnostic"):
            result["records"] = response["diagnostic"]
        if flags["cache_enabled"]:
            store.put_cache(cache_key, message, provider, result)
        return jsonify({"ok": True, "cached": False, "route": decision, **result})
    except Exception as exc:
        fallback = "local"
        local_route = {**decision, "provider": fallback, "model_role": "local", "reason": f"Fallback after provider error: {exc}"}
        response, latency_ms, model = call_provider(message, local_route)
        store.log_usage(decision["provider"], provider_model(decision["provider"], decision["model_role"]), decision["task_type"], "failed", int((time.perf_counter() - started) * 1000), str(exc))
        store.log_usage(fallback, model, decision["task_type"], "fallback", latency_ms, "local fallback")
        store.log_audit("provider_fallback", actor, decision["provider"], str(exc))
        return jsonify({"ok": True, "cached": False, "route": decision, "fallback": fallback, "provider_error": str(exc), "provider": fallback, "model": model, **response})


@app.route("/api/pmoai/usage", methods=["GET", "OPTIONS"])
def usage():
    if request.method == "OPTIONS":
        return ("", 204)
    return jsonify({"ok": True, "usage": store.usage_summary()})


@app.route("/api/pmoai/records/status", methods=["GET", "OPTIONS"])
def records_status():
    if request.method == "OPTIONS":
        return ("", 204)
    scope = str(request.args.get("scope", "all")).strip() or "all"
    diagnostic = diagnose_records(scope, include_deleted=True)
    return jsonify({
        "ok": True,
        "default_response": DEFAULT_RESPONSE,
        "checklist": CHECKLIST,
        "records": diagnostic,
    })


@app.route("/api/pmoai/records/diagnose", methods=["POST", "OPTIONS"])
def records_diagnose():
    if request.method == "OPTIONS":
        return ("", 204)
    payload = request.get_json(force=True, silent=True) or {}
    scope = str(payload.get("scope", "all")).strip() or "all"
    include_deleted = bool(payload.get("include_deleted", True))
    actor = request.headers.get("X-PMOAI-User", "dashboard")
    diagnostic = diagnose_records(scope, include_deleted=include_deleted)
    store.log_audit("records_diagnose", actor, "local", f"scope={scope}; rows={diagnostic['totals']['rows']}")
    return jsonify({"ok": True, "records": diagnostic})


@app.route("/api/pmoai/records/resync", methods=["POST", "OPTIONS"])
def records_resync():
    if request.method == "OPTIONS":
        return ("", 204)
    payload = request.get_json(force=True, silent=True) or {}
    scope = str(payload.get("scope", "all")).strip() or "all"
    actor = request.headers.get("X-PMOAI-User", "dashboard")
    diagnostic = diagnose_records(scope, include_deleted=True)
    store.log_audit("records_resync_requested", actor, "local", f"scope={scope}; source_count={diagnostic['audit']['source_count']}")
    return jsonify({
        "ok": True,
        "message": "Manual re-sync requested. PMOAI re-inspected local historical sources; external source re-sync requires the source connector permissions.",
        "records": diagnostic,
    })


if __name__ == "__main__":
    app.run(host=SETTINGS.host, port=SETTINGS.port, debug=False)
