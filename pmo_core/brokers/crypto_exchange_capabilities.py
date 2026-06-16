"""Placeholder external crypto exchange capability map.

PMO can use Alpaca crypto through alpaca_capabilities. External crypto
exchanges and derivatives remain scan-only until a real adapter is added.
"""
from __future__ import annotations

from typing import Any, Dict

supported_asset_classes = []
supported_order_types_by_asset_class: Dict[str, list[str]] = {}
supported_time_in_force = []
supports_fractional = True
supports_shorting = False
supports_options = False
supports_futures = False
supports_forex = False
supports_crypto = False
supports_bonds = False
supports_mutual_funds = False
paper_supported = False
live_supported = False
account_permission_requirements = {"CRYPTO": ["exchange_account", "jurisdiction_check"]}
data_feed_requirements = {"CRYPTO": ["exchange_market_data"]}
known_limitations = ["No external crypto exchange adapter is configured. Crypto derivatives stay scan-only."]
CAPABILITIES = {k: v for k, v in globals().items() if k in {
    "supported_asset_classes", "supported_order_types_by_asset_class", "supported_time_in_force",
    "supports_fractional", "supports_shorting", "supports_options", "supports_futures",
    "supports_forex", "supports_crypto", "supports_bonds", "supports_mutual_funds",
    "paper_supported", "live_supported", "account_permission_requirements",
    "data_feed_requirements", "known_limitations",
}}
CAPABILITIES["broker"] = "crypto_exchange"


def validate_order_capability(order_request: Dict[str, Any], account: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {"ok": False, "reason": "No external crypto exchange adapter configured; scan-only."}

