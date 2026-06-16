from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable
from dotenv import load_dotenv


def load_environment(env_files: Iterable[Path]) -> None:
    for env_file in env_files:
        if Path(env_file).exists():
            load_dotenv(env_file, override=True)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y"}


def first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return ""
