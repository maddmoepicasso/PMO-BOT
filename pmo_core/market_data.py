from __future__ import annotations

import re
from typing import Any, Dict


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def normalize_crypto_symbol(symbol: str) -> str:
    clean = str(symbol or "").strip().upper().replace("-", "/")
    if "/" in clean:
        return clean
    known = {"BTC", "ETH", "SOL", "DOGE", "LTC", "BCH", "AVAX", "LINK", "UNI", "AAVE", "MKR"}
    if clean.endswith("USD") and clean[:-3] in known:
        return f"{clean[:-3]}/USD"
    return clean


def detect_market(symbol: str, requested: str = "AUTO") -> str:
    requested = str(requested or "AUTO").strip().upper()
    if requested in {"STOCK", "CRYPTO", "OPTION"}:
        return requested
    clean = str(symbol or "").strip().upper()
    if "/" in clean or (clean.endswith("USD") and len(clean) <= 8):
        return "CRYPTO"
    if re.search(r"\d{6}[CP]\d{8}$", clean):
        return "OPTION"
    return "STOCK"


class MarketDataFacade:
    """Adapter around a PMOBot instance so market data can be moved out safely."""
    def __init__(self, bot: Any):
        self.bot = bot

    def latest_price(self, symbol: str, market: str = "AUTO") -> Dict[str, Any]:
        return self.bot.get_latest_price(symbol, market)

    def bars(self, symbol: str, market: str = "AUTO", days: int = 5) -> Dict[str, Any]:
        return self.bot.get_bars(symbol, market, days)

    def regime(self) -> Dict[str, Any]:
        return self.bot.market_regime()
