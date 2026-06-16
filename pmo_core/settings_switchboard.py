from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

SETTING_ALIAS_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("ALPACA_PAPER", "PAPER"),
    ("ORDER_AUTOMATION_ENABLED", "ALPACA_ORDER_AUTOMATION"),
    ("PMO_DRY_RUN_ORDERS", "ALPACA_DRY_RUN_MODE"),
    ("PMO_MAX_DAILY_TRADES", "MAX_DAILY_TRADES"),
)


def sync_setting_aliases(settings: Dict[str, Any], changed_name: str = "") -> None:
    for primary, alias in SETTING_ALIAS_PAIRS:
        if changed_name == primary and primary in settings:
            settings[alias] = settings[primary]
        elif changed_name == alias and alias in settings:
            settings[primary] = settings[alias]
        elif primary in settings and alias not in settings:
            settings[alias] = settings[primary]
        elif alias in settings and primary not in settings:
            settings[primary] = settings[alias]
        elif primary in settings and alias in settings and not changed_name:
            settings[alias] = settings[primary]


def read_literal_settings_file(path: Path) -> Dict[str, Any]:
    loaded: Dict[str, Any] = {}
    if not path.exists():
        return loaded
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        target = None
        value_node = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
            value_node = node.value
        if target and target.isupper() and value_node is not None:
            try:
                loaded[target] = ast.literal_eval(value_node)
            except Exception:
                loaded[f"{target}_ERROR"] = "setting value must be a Python literal"
    return loaded


def write_settings_file(path: Path, settings: Dict[str, Any], ordered_keys: Iterable[str]) -> None:
    lines = ["# PMO BOT local settings", "# Secrets belong in .env, not in this file.", ""]
    for key in list(ordered_keys) + sorted(k for k in settings if k.isupper() and k not in ordered_keys and not k.endswith("_ERROR")):
        if key in settings:
            lines.append(f"{key} = {repr(settings[key])}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
