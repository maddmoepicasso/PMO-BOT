from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests


ONESIGNAL_API_URL = "https://api.onesignal.com/notifications"


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return str(value).strip()
    return ""


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = str(value).split(",")
    return [str(item).strip() for item in raw if str(item).strip()]


def _append_event(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                rows = existing[-250:]
        except Exception:
            rows = []
    rows.append(row)
    path.write_text(json.dumps(rows[-250:], indent=2, sort_keys=True), encoding="utf-8")


def pmo_onesignal_config(settings: Dict[str, Any]) -> Dict[str, Any]:
    web_app_id = (
        _first_env("ONESIGNAL_WEB_APP_ID", "PMO_ONESIGNAL_WEB_APP_ID")
        or str(settings.get("PMO_ONESIGNAL_WEB_APP_ID") or "").strip()
    )
    app_id = (
        _first_env("ONESIGNAL_APP_ID", "PMO_ONESIGNAL_APP_ID")
        or web_app_id
        or str(settings.get("PMO_ONESIGNAL_APP_ID") or "").strip()
    )
    api_key = _first_env("ONESIGNAL_REST_API_KEY", "ONESIGNAL_APP_API_KEY", "PMO_ONESIGNAL_REST_API_KEY")
    default_segment = str(settings.get("PMO_ONESIGNAL_DEFAULT_SEGMENT") or "Subscribed Users").strip()
    enabled = _bool(settings.get("ENABLE_PMO_ONESIGNAL_NOTIFICATIONS"), False)
    return {
        "enabled": enabled,
        "app_id": app_id,
        "web_sdk_enabled": _bool(settings.get("PMO_ONESIGNAL_WEB_SDK_ENABLED"), True),
        "web_app_id": web_app_id or app_id,
        "allow_localhost_as_secure_origin": _bool(settings.get("PMO_ONESIGNAL_ALLOW_LOCALHOST_AS_SECURE_ORIGIN"), True),
        "api_key": api_key,
        "default_segment": default_segment or "Subscribed Users",
        "timeout_seconds": int(float(settings.get("PMO_ONESIGNAL_TIMEOUT_SECONDS") or 15)),
        "allow_push": _bool(settings.get("PMO_ONESIGNAL_ALLOW_PUSH"), True),
        "allow_email": _bool(settings.get("PMO_ONESIGNAL_ALLOW_EMAIL"), False),
        "allow_sms": _bool(settings.get("PMO_ONESIGNAL_ALLOW_SMS"), False),
    }


def pmo_onesignal_status(settings: Dict[str, Any], events_file: Optional[Path] = None) -> Dict[str, Any]:
    cfg = pmo_onesignal_config(settings)
    recent = []
    if events_file and events_file.exists():
        try:
            data = json.loads(events_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                recent = data[-5:]
        except Exception:
            recent = []
    ready = bool(cfg["enabled"] and cfg["app_id"] and cfg["api_key"])
    web_sdk_ready = bool(cfg["web_sdk_enabled"] and cfg["web_app_id"])
    return {
        "ok": True,
        "provider": "OneSignal",
        "enabled": cfg["enabled"],
        "ready": ready,
        "web_sdk": {
            "enabled": cfg["web_sdk_enabled"],
            "ready": web_sdk_ready,
            "app_id_configured": bool(cfg["web_app_id"]),
            "worker_path": "/OneSignalSDKWorker.js",
            "updater_worker_path": "/OneSignalSDKUpdaterWorker.js",
            "allow_localhost_as_secure_origin": cfg["allow_localhost_as_secure_origin"],
            "safe_note": "Browser Web SDK subscriptions are separate from PMO server-side REST notification sending.",
        },
        "app_id_configured": bool(cfg["app_id"]),
        "api_key_configured": bool(cfg["api_key"]),
        "default_segment": cfg["default_segment"],
        "channels": {
            "push": cfg["allow_push"],
            "email": cfg["allow_email"],
            "sms": cfg["allow_sms"],
        },
        "endpoint": ONESIGNAL_API_URL,
        "recent_events": recent,
        "required_env": ["ONESIGNAL_APP_ID or PMO_ONESIGNAL_WEB_APP_ID", "ONESIGNAL_REST_API_KEY for server-side sends"],
        "safe_note": "OneSignal notifications are alerts only. They never place orders, unlock live trading, or change PMO settings.",
        "orders_placed": False,
        "live_unlocked": False,
        "settings_changed": False,
    }


def build_onesignal_message(settings: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = pmo_onesignal_config(settings)
    title = str(payload.get("title") or payload.get("heading") or "PMO Bot Alert").strip()[:120]
    message = str(payload.get("message") or payload.get("body") or "PMO Bot notification").strip()[:1500]
    url = str(payload.get("url") or "").strip()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    data = {**data, "source": "PMO_BOT", "notification_only": True}

    request_body: Dict[str, Any] = {
        "app_id": cfg["app_id"],
        "target_channel": str(payload.get("target_channel") or "push").strip().lower(),
        "headings": {"en": title},
        "contents": {"en": message},
        "data": data,
    }
    if url:
        request_body["url"] = url

    include_aliases = payload.get("include_aliases")
    external_ids = _safe_list(payload.get("external_ids") or payload.get("external_id"))
    subscription_ids = _safe_list(payload.get("subscription_ids") or payload.get("subscription_id"))
    included_segments = _safe_list(payload.get("included_segments") or payload.get("segment") or cfg["default_segment"])
    filters = payload.get("filters")

    target_methods = sum(bool(x) for x in [include_aliases, external_ids, subscription_ids, included_segments, filters])
    if target_methods > 1:
        raise ValueError("Use exactly one OneSignal targeting method: aliases, external_ids, subscription_ids, segments, or filters.")

    if include_aliases and isinstance(include_aliases, dict):
        request_body["include_aliases"] = include_aliases
    elif external_ids:
        request_body["include_aliases"] = {"external_id": external_ids}
    elif subscription_ids:
        request_body["include_subscription_ids"] = subscription_ids
        request_body.pop("target_channel", None)
    elif filters and isinstance(filters, list):
        request_body["filters"] = filters
        request_body.pop("target_channel", None)
    else:
        request_body["included_segments"] = included_segments or [cfg["default_segment"]]

    return request_body


def send_onesignal_notification(settings: Dict[str, Any], payload: Dict[str, Any], events_file: Path) -> Dict[str, Any]:
    cfg = pmo_onesignal_config(settings)
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "OneSignal",
        "title": str(payload.get("title") or payload.get("heading") or "PMO Bot Alert")[:120],
        "dry_run": bool(payload.get("dry_run", False)),
        "orders_placed": False,
        "live_unlocked": False,
        "settings_changed": False,
    }
    if not cfg["enabled"]:
        event.update({"ok": False, "error": "ENABLE_PMO_ONESIGNAL_NOTIFICATIONS is false."})
        _append_event(events_file, event)
        return event
    if not cfg["app_id"] or not cfg["api_key"]:
        event.update({"ok": False, "error": "ONESIGNAL_APP_ID or ONESIGNAL_REST_API_KEY missing."})
        _append_event(events_file, event)
        return event

    request_body = build_onesignal_message(settings, payload)
    if bool(payload.get("dry_run", False)):
        safe_body = dict(request_body)
        safe_body["app_id"] = "***configured***"
        event.update({"ok": True, "dry_run": True, "request": safe_body})
        _append_event(events_file, event)
        return event

    try:
        response = requests.post(
            ONESIGNAL_API_URL,
            headers={
                "Authorization": f"Key {cfg['api_key']}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            json=request_body,
            timeout=cfg["timeout_seconds"],
        )
        try:
            body: Any = response.json()
        except Exception:
            body = {"text": response.text[:1000]}
        event.update({
            "ok": 200 <= response.status_code < 300,
            "status_code": response.status_code,
            "response": body,
        })
    except Exception as exc:
        event.update({"ok": False, "error": str(exc)})
    _append_event(events_file, event)
    return event


def build_pmo_alert_payload(title: str, message: str, level: str = "INFO", url: str = "", **extra: Any) -> Dict[str, Any]:
    return {
        "title": f"PMO {level}: {title}".strip(),
        "message": message,
        "url": url,
        "data": {"level": level, **extra},
    }
