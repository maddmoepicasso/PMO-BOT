from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, Iterable, List

import requests


PY_DIR = Path(__file__).resolve().parent
PMO_ROOT = PY_DIR.parent if PY_DIR.name.lower() == "python" else PY_DIR
BOT_ENV = PY_DIR / ".env"
PLAYZ_ENV = PMO_ROOT / "PMO_PLAYZ_GROWTH_PANEL" / ".env"
REDIRECT_PORT = 8765
REDIRECT_PATH = "/oauth2callback"
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}{REDIRECT_PATH}"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]


def read_env_file(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def first_value(keys: Iterable[str], *envs: Dict[str, str]) -> str:
    for key in keys:
        if os.getenv(key):
            return str(os.getenv(key)).strip()
        for env in envs:
            if env.get(key):
                return str(env[key]).strip()
    return ""


def set_env_lines(path: Path, updates: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    seen = set()
    output: List[str] = []
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


class OAuthHandler(BaseHTTPRequestHandler):
    server_version = "PMOYouTubeOAuth/1.0"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if parsed.path != REDIRECT_PATH:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"PMO Playz OAuth helper is waiting for Google's callback.")
            return
        self.server.oauth_code = (params.get("code") or [""])[0]  # type: ignore[attr-defined]
        self.server.oauth_state = (params.get("state") or [""])[0]  # type: ignore[attr-defined]
        self.server.oauth_error = (params.get("error") or [""])[0]  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"""<!doctype html><html><head><title>PMO Playz YouTube Connected</title>
<style>body{font-family:Arial,sans-serif;background:#090b12;color:#f4f7ff;display:grid;min-height:100vh;place-items:center}.card{max-width:680px;border:1px solid #2f3d55;background:#121724;border-radius:8px;padding:24px}h1{color:#d7a84f}</style>
</head><body><div class="card"><h1>PMO Playz YouTube OAuth received.</h1><p>You can close this tab and return to the terminal.</p><p>PMO will save the refresh token into the local .env files.</p></div></body></html>"""
        )

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        return


def wait_for_code(expected_state: str, timeout_seconds: int) -> str:
    server = HTTPServer(("127.0.0.1", REDIRECT_PORT), OAuthHandler)
    server.oauth_code = ""  # type: ignore[attr-defined]
    server.oauth_state = ""  # type: ignore[attr-defined]
    server.oauth_error = ""  # type: ignore[attr-defined]

    def serve() -> None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline and not getattr(server, "oauth_code", "") and not getattr(server, "oauth_error", ""):
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    thread.join(timeout_seconds + 2)
    error = getattr(server, "oauth_error", "")
    code = getattr(server, "oauth_code", "")
    state = getattr(server, "oauth_state", "")
    server.server_close()
    if error:
        raise RuntimeError(f"Google OAuth returned an error: {error}")
    if not code:
        raise RuntimeError("No OAuth code received. Try again and finish the Google approval screen.")
    if state != expected_state:
        raise RuntimeError("OAuth state mismatch. Token request was blocked for safety.")
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="Get and save a YouTube OAuth refresh token for PMO Playz.")
    parser.add_argument("--timeout", type=int, default=240, help="Seconds to wait for Google OAuth callback.")
    parser.add_argument("--print-token", action="store_true", help="Print the refresh token after saving it.")
    parser.add_argument("--check", action="store_true", help="Check whether YouTube OAuth values are present without opening Google login.")
    args = parser.parse_args()

    bot_env = read_env_file(BOT_ENV)
    playz_env = read_env_file(PLAYZ_ENV)
    client_id = first_value(["YOUTUBE_CLIENT_ID", "PMO_PLAYZ_YOUTUBE_CLIENT_ID"], playz_env, bot_env)
    client_secret = first_value(["YOUTUBE_CLIENT_SECRET", "PMO_PLAYZ_YOUTUBE_CLIENT_SECRET"], playz_env, bot_env)
    existing_refresh_token = first_value(["YOUTUBE_REFRESH_TOKEN", "PMO_PLAYZ_YOUTUBE_REFRESH_TOKEN"], playz_env, bot_env)
    if args.check:
        print(json.dumps({
            "client_id_ready": bool(client_id),
            "client_secret_ready": bool(client_secret),
            "refresh_token_ready": bool(existing_refresh_token),
            "bot_env": str(BOT_ENV),
            "playz_env": str(PLAYZ_ENV),
        }, indent=2))
        return 0 if client_id and client_secret else 1
    if not client_id or not client_secret:
        print("ERROR: YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in PMO Playz or PMO BOT .env first.")
        return 1

    state = secrets.token_urlsafe(24)
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    print("PMO Playz YouTube OAuth helper")
    print(f"Redirect URI: {REDIRECT_URI}")
    print("Opening Google login in your browser...")
    print("If the browser does not open, paste this URL manually:")
    print(auth_url)
    webbrowser.open(auth_url)

    code = wait_for_code(state, args.timeout)
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    payload = response.json()
    if response.status_code >= 400:
        print("ERROR: Google token exchange failed.")
        print(json.dumps({k: v for k, v in payload.items() if k != "refresh_token"}, indent=2))
        return 1
    refresh_token = str(payload.get("refresh_token") or "").strip()
    if not refresh_token:
        print("ERROR: Google did not return a refresh_token.")
        print("Fix: rerun this helper and make sure the OAuth URL uses prompt=consent, then approve the app.")
        return 1

    updates = {
        "YOUTUBE_REFRESH_TOKEN": refresh_token,
        "PMO_PLAYZ_YOUTUBE_REFRESH_TOKEN": refresh_token,
    }
    set_env_lines(BOT_ENV, updates)
    set_env_lines(PLAYZ_ENV, updates)
    print("SUCCESS: YouTube refresh token saved to:")
    print(f"- {BOT_ENV}")
    print(f"- {PLAYZ_ENV}")
    print("Restart PMO Playz after this so it reloads the token.")
    if args.print_token:
        print(refresh_token)
    else:
        print("Refresh token was not printed. Use --print-token only if you need to view it.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCanceled.")
        raise SystemExit(130)
