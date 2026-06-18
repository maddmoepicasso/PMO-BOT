"""Natural-language command parser for PMO Desk Commander AI."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict


UNSAFE_PATTERNS = [
    (r"\b(go live|unlock live|arm live|live master|enable live)\b", "enable_live_trading"),
    (r"\b(place|submit|send|execute)\b.*\b(order|trade)\b", "place_order"),
    (r"\b(buy|sell|short)\b\s+[A-Z]{1,6}\b", "place_order"),
    (r"\b(approve)\b.*\b(trade|paper trade|order)\b", "approve_trade"),
    (r"\b(disable|turn off)\b.*\b(risk|guard|firewall|breaker)\b", "disable_risk_guard"),
    (r"\b(show|print|export|reveal)\b.*\b(secret|token|key|password)\b", "show_secret"),
    (r"\b(delete|wipe|remove)\b.*\b(data|journal|logs|trades)\b", "delete_data"),
]


COMMAND_PATTERNS = [
    (r"\b(status|how is pmo|bot status|health)\b", "get_pmo_status", 0.86),
    (r"\b(live readiness|readiness|live lock|ready for live)\b", "get_live_readiness", 0.88),
    (r"\b(safety|safe mode|risk status|firewall status)\b", "get_safety_status", 0.84),
    (r"\b(refresh connections|connection refresh|alpaca sync|broker sync status)\b", "refresh_connections", 0.86),
    (r"\b(switchboard audit|audit settings|settings audit)\b", "run_switchboard_audit", 0.88),
    (r"\b(paper proof|proof report|proof center|v112 proof)\b", "run_paper_proof", 0.86),
    (r"\b(refresh watchlist|auto watchlist|watchlist refresh)\b", "refresh_watchlist", 0.84),
    (r"\b(backtest|back test|simulator)\b", "run_backtest", 0.86),
    (r"\b(cobr|microstructure sim|order book sim)\b", "run_cobr_sim", 0.86),
    (r"\b(firewall check|execution firewall|run firewall)\b", "run_firewall_check", 0.86),
    (r"\b(pre session|pre-session|checklist|morning checklist)\b", "run_pre_session_checklist", 0.84),
    (r"\b(what is missing|what's missing|why blocked|why not|next action|fix next)\b", "explain_what_is_missing", 0.9),
    (r"\b(sync journal|sync trades|sync paper|close hits|close target|close stop)\b", "sync_journal", 0.88),
    (r"\b(paper safe|safe baseline|return safe)\b", "apply_paper_safe_baseline", 0.85),
    (r"\b(data collection status|collection status|how many collection trades|trades collected|150 trade target)\b", "get_data_collection_status", 0.9),
    (r"\b(enable|start|resume|continue|turn on)\b.*\b(data collection|collection mode|collecting data|collect data|150 trades)\b", "enable_data_collection", 0.88),
    (r"\b(enable paper executor|paper executor collection|paper collection)\b", "enable_paper_executor_collection", 0.85),
    (r"\b(crypto research only|crypto safe|lock crypto)\b", "return_crypto_research_only", 0.85),
    (r"\b(code review|review code|scan code)\b", "review_code", 0.88),
    (r"\b(patch plan|repair plan|fix plan)\b", "make_patch_plan", 0.82),
    (r"\b(stop voice|mute|stop listening)\b", "stop_voice", 0.82),
]


SECTION_PATTERNS = {
    "safety": "panelFirewallLab",
    "firewall": "panelFirewallLab",
    "readiness": "panelReadiness",
    "journal": "panelJournal",
    "truth": "panelTruth",
    "watchlist": "panelDna",
    "chart": "panelTradingViewChart",
    "settings": "panelSwitchboard",
    "switchboard": "panelSwitchboard",
    "backtest": "panelFirewallLab",
    "ai": "panelDeskCommanderAI",
}


def _voice_command_dir() -> Path:
    env_path = os.getenv("PMO_VOICE_COMMAND_DIR", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return Path(__file__).resolve().parents[1] / "pmo_voice_commands"


def _read_pack(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {
            "enabled": False,
            "pack": path.stem,
            "file": str(path),
            "error": str(exc),
            "commands": [],
        }


def load_voice_command_packs() -> list[Dict[str, Any]]:
    folder = _voice_command_dir()
    if not folder.exists():
        return []
    packs: list[Dict[str, Any]] = []
    for path in sorted(folder.glob("*.json")):
        if path.name.startswith("_"):
            continue
        pack = _read_pack(path)
        pack.setdefault("pack", path.stem)
        pack.setdefault("file", str(path))
        packs.append(pack)
    return packs


def voice_command_catalog() -> Dict[str, Any]:
    packs = load_voice_command_packs()
    enabled_packs = [pack for pack in packs if pack.get("enabled", True)]
    commands = []
    examples = []
    blocked_count = 0
    for pack in enabled_packs:
        for command in pack.get("commands", []) or []:
            if not isinstance(command, dict) or command.get("enabled", True) is False:
                continue
            item = {
                "pack": pack.get("pack"),
                "id": command.get("id", ""),
                "label": command.get("label", command.get("id", "")),
                "tool": command.get("tool", ""),
                "intent": command.get("intent", "tool"),
                "blocked": bool(command.get("blocked", False)),
                "phrases": command.get("phrases", []),
                "examples": command.get("examples", []),
                "arguments": command.get("arguments", {}),
            }
            if item["blocked"]:
                blocked_count += 1
            commands.append(item)
            for example in item["examples"] or item["phrases"] or []:
                if len(examples) < 24:
                    examples.append(str(example))
                    break
    return {
        "ok": True,
        "folder": str(_voice_command_dir()),
        "packs": packs,
        "pack_count": len(packs),
        "enabled_pack_count": len(enabled_packs),
        "command_count": len(commands),
        "blocked_command_count": blocked_count,
        "commands": commands,
        "examples": examples,
        "safety_note": "Voice command packs only map phrases to registered PMO Desk Commander tools. The backend firewall still blocks live/order/secrets/destructive actions.",
    }


def _phrase_matches(phrase: Any, lowered: str) -> bool:
    phrase_text = re.sub(r"\s+", " ", str(phrase or "").strip().lower())
    return bool(phrase_text) and phrase_text in lowered


def _pack_command_match(text: str, input_type: str) -> Dict[str, Any]:
    lowered = text.lower()
    candidates: list[Dict[str, Any]] = []
    for pack in load_voice_command_packs():
        if pack.get("enabled", True) is False:
            continue
        pack_name = str(pack.get("pack") or "")
        for command in pack.get("commands", []) or []:
            if not isinstance(command, dict) or command.get("enabled", True) is False:
                continue
            matched = ""
            match_type = ""
            for pattern in command.get("patterns", []) or []:
                try:
                    if re.search(str(pattern), lowered, re.IGNORECASE):
                        matched = str(pattern)
                        match_type = "pattern"
                        break
                except re.error:
                    continue
            if not matched:
                for phrase in command.get("phrases", []) or []:
                    if _phrase_matches(phrase, lowered):
                        matched = str(phrase)
                        match_type = "phrase"
                        break
            if not matched:
                continue
            confidence = float(command.get("confidence", 0.86))
            result = {
                "ok": True,
                "intent": command.get("intent", "blocked" if command.get("blocked") else "tool"),
                "tool": command.get("tool", ""),
                "confidence": confidence,
                "input_type": input_type,
                "text": text,
                "arguments": command.get("arguments", {}) if isinstance(command.get("arguments"), dict) else {},
                "voice_pack": pack_name,
                "command_id": command.get("id", ""),
                "matched": matched,
                "match_type": match_type,
                "_match_score": (1 if command.get("blocked") else 0, len(matched), confidence),
            }
            if command.get("blocked"):
                result.update({
                    "intent": "blocked",
                    "blocked": True,
                    "reason": command.get("reason") or "Command matches PMO voice command blocked action policy.",
                })
            candidates.append(result)
    if not candidates:
        return {}
    best = sorted(candidates, key=lambda item: item.get("_match_score", (0, 0, 0)), reverse=True)[0]
    best.pop("_match_score", None)
    return best


def _blocked_command(text: str) -> Dict[str, Any]:
    pack_match = _pack_command_match(text, "text")
    if pack_match.get("blocked"):
        return pack_match
    for pattern, tool in UNSAFE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {
                "ok": True,
                "intent": "blocked",
                "tool": tool,
                "confidence": 0.99,
                "blocked": True,
                "reason": "Command matches PMO Desk Commander blocked action policy.",
            }
    return {}


def parse_ai_command(text: str, input_type: str = "text") -> Dict[str, Any]:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    lowered = clean.lower()
    if not clean:
        return {"ok": False, "intent": "clarify", "tool": "clarify", "confidence": 0.0, "message": "No command text supplied."}

    blocked = _blocked_command(clean)
    if blocked:
        blocked["input_type"] = input_type
        blocked["text"] = clean
        return blocked

    pack_match = _pack_command_match(clean, input_type)
    if pack_match:
        return pack_match

    open_match = re.search(r"\b(open|show|go to|scroll to)\b\s+(?P<section>[a-z0-9 _-]+)", lowered)
    if open_match:
        section_text = open_match.group("section")
        for key, section_id in SECTION_PATTERNS.items():
            if key in section_text:
                return {
                    "ok": True,
                    "intent": "frontend",
                    "tool": "open_dashboard_section",
                    "confidence": 0.82,
                    "input_type": input_type,
                    "text": clean,
                    "arguments": {"section_id": section_id, "section": key},
                }

    for pattern, tool, confidence in COMMAND_PATTERNS:
        if re.search(pattern, lowered, re.IGNORECASE):
            args: Dict[str, Any] = {}
            if tool == "sync_journal":
                args = {"close_hits": bool(re.search(r"\b(close hits|target|stop)\b", lowered)), "days": 30, "limit": 500}
            elif tool == "run_backtest":
                args = {"record": False}
            elif tool == "run_cobr_sim":
                args = {"record": False}
            elif tool == "enable_data_collection":
                trade_match = re.search(r"\b(?P<count>\d{2,3})\s*(?:trade|trades)\b", lowered)
                max_trades = int(trade_match.group("count")) if trade_match else 150
                args = {"max_trades": max(5, min(150, max_trades)), "timeout_minutes": 10080}
            elif tool in {"apply_paper_safe_baseline", "enable_paper_executor_collection", "return_crypto_research_only"}:
                args = {"apply": True}
            return {
                "ok": True,
                "intent": "tool",
                "tool": tool,
                "confidence": confidence,
                "input_type": input_type,
                "text": clean,
                "arguments": args,
            }

    return {
        "ok": True,
        "intent": "chat",
        "tool": "explain_what_is_missing",
        "confidence": 0.55,
        "input_type": input_type,
        "text": clean,
        "arguments": {},
        "needs_clarification": True,
    }
