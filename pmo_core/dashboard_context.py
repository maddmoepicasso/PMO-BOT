from __future__ import annotations

from typing import Any, Dict


def dashboard_context(bot: Any) -> Dict[str, Any]:
    account = bot.account_snapshot()
    health = bot.connection_check()
    regime = bot.market_regime()
    return {"account": account, "health": health, "regime": regime, "settings": getattr(bot, "settings", {})}
