from __future__ import annotations

from typing import Any, Dict


class TradingViewBridgeFacade:
    def __init__(self, bot: Any):
        self.bot = bot

    def evaluate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.bot.evaluate_tradingview_alert(payload)

    def status(self) -> Dict[str, Any]:
        settings = getattr(self.bot, "settings", {})
        return {"mode": settings.get("TRADINGVIEW_ALERT_MODE", "SCAN_ONLY"), "secret_configured": settings.get("TRADINGVIEW_WEBHOOK_SECRET") not in {"", "CHANGE_ME_SECRET"}}
