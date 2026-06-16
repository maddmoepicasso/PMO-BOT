from __future__ import annotations

import hashlib
import secrets
import uuid
from pathlib import Path
from typing import Any, Dict
from .reporting import read_json_file, write_json_file

ADMIN_TOKEN_SCHEME = "pbkdf2_sha256"
ADMIN_TOKEN_PBKDF2_ITERATIONS = 260_000


def hash_token(token: str, salt: str, iterations: int = ADMIN_TOKEN_PBKDF2_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", token.encode("utf-8"), salt.encode("utf-8"), max(100000, int(iterations))).hex()


def token_valid(token: Any, env_token: str = "", local_file: Path | None = None) -> bool:
    clean = str(token or "").strip()
    if not clean:
        return False
    if env_token:
        return secrets.compare_digest(clean, env_token)
    if not local_file:
        return False
    local = read_json_file(local_file, {})
    salt = str(local.get("salt") or "")
    token_hash = str(local.get("token_hash") or "")
    if not salt or not token_hash:
        return False
    return secrets.compare_digest(hash_token(clean, salt, int(local.get("iterations") or ADMIN_TOKEN_PBKDF2_ITERATIONS)), token_hash)


def create_local_token_file(path: Path, token: str) -> Dict[str, Any]:
    clean = str(token or "").strip()
    if len(clean) < 8:
        raise ValueError("Admin token must be at least 8 characters.")
    salt = uuid.uuid4().hex
    payload = {"token_hash": hash_token(clean, salt), "salt": salt, "scheme": ADMIN_TOKEN_SCHEME, "iterations": ADMIN_TOKEN_PBKDF2_ITERATIONS, "raw_token_visible": False}
    write_json_file(path, payload)
    return {"ok": True, "file": str(path), "source": "local_hash"}
