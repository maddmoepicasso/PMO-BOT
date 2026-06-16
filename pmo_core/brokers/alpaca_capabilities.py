"""Alpaca capability map used by the PMO asset universe.

This is a capability description, not an execution adapter.
"""
from __future__ import annotations

from typing import Any, Dict


supported_asset_classes = [
    "STOCK", "ETF", "ETP", "ETN", "LEVERAGED_ETF", "INVERSE_ETF",
    "SINGLE_STOCK_ETF", "REIT", "BDC", "ADR", "COMMODITY_ETF",
    "CURRENCY_ETF", "VOLATILITY_ETP", "CRYPTO_SPOT",
    "STOCK_OPTION", "ETF_OPTION",
]

supported_order_types_by_asset_class = {
    "STOCK": ["market", "limit", "stop", "stop_limit", "trailing_stop"],
    "ETF": ["market", "limit", "stop", "stop_limit", "trailing_stop"],
    "CRYPTO_SPOT": ["market", "limit"],
    "STOCK_OPTION": ["market", "limit"],
    "ETF_OPTION": ["market", "limit"],
}
supported_time_in_force = ["day", "gtc", "opg", "cls", "ioc", "fok"]
supports_fractional = True
supports_shorting = True
supports_options = True
supports_futures = False
supports_forex = False
supports_crypto = True
supports_bonds = False
supports_mutual_funds = False
paper_supported = True
live_supported = False
account_permission_requirements = {
    "STOCK_OPTION": ["options_approval"],
    "ETF_OPTION": ["options_approval"],
    "CRYPTO_SPOT": ["crypto_enabled"],
}
data_feed_requirements = {
    "STOCK": ["stock_market_data"],
    "ETF": ["stock_market_data"],
    "CRYPTO_SPOT": ["crypto_market_data"],
    "STOCK_OPTION": ["option_market_data"],
    "ETF_OPTION": ["option_market_data"],
}
known_limitations = [
    "No futures, forex spot, bonds, mutual funds, prediction markets, or tokenized assets.",
    "Options permission and account level must be checked before execution.",
    "Live capability remains controlled by PMO live locks and asset proof gates.",
]

CAPABILITIES = {
    name: value
    for name, value in globals().items()
    if name
    in {
        "supported_asset_classes", "supported_order_types_by_asset_class",
        "supported_time_in_force", "supports_fractional", "supports_shorting",
        "supports_options", "supports_futures", "supports_forex", "supports_crypto",
        "supports_bonds", "supports_mutual_funds", "paper_supported", "live_supported",
        "account_permission_requirements", "data_feed_requirements", "known_limitations",
    }
}
CAPABILITIES["broker"] = "alpaca"


def validate_order_capability(order_request: Dict[str, Any], account: Dict[str, Any] | None = None) -> Dict[str, Any]:
    asset_class = str(order_request.get("asset_class", "")).upper()
    order_type = str(order_request.get("order_type", "market")).lower()
    if asset_class not in supported_asset_classes:
        return {"ok": False, "reason": f"Alpaca capability map does not support {asset_class}."}
    allowed = supported_order_types_by_asset_class.get(asset_class, supported_order_types_by_asset_class.get("STOCK", []))
    if order_type not in allowed:
        return {"ok": False, "reason": f"{order_type} is not allowed for {asset_class} on Alpaca capability map."}
    return {"ok": True, "reason": "Capability check passed; PMO safety gates still apply."}

