"""Placeholder fixed-income capability map. Bonds and funds remain scan-only."""
from __future__ import annotations

from typing import Any, Dict

supported_asset_classes = []
supported_order_types_by_asset_class: Dict[str, list[str]] = {}
supported_time_in_force = []
supports_fractional = False
supports_shorting = False
supports_options = False
supports_futures = False
supports_forex = False
supports_crypto = False
supports_bonds = False
supports_mutual_funds = False
paper_supported = False
live_supported = False
account_permission_requirements = {"FIXED_INCOME": ["fixed_income_account_access"]}
data_feed_requirements = {"FIXED_INCOME": ["fixed_income_data_feed"]}
known_limitations = ["No fixed-income or mutual-fund trading API is configured. These assets stay scan-only."]
CAPABILITIES = {k: v for k, v in globals().items() if k in {
    "supported_asset_classes", "supported_order_types_by_asset_class", "supported_time_in_force",
    "supports_fractional", "supports_shorting", "supports_options", "supports_futures",
    "supports_forex", "supports_crypto", "supports_bonds", "supports_mutual_funds",
    "paper_supported", "live_supported", "account_permission_requirements",
    "data_feed_requirements", "known_limitations",
}}
CAPABILITIES["broker"] = "fixed_income"


def validate_order_capability(order_request: Dict[str, Any], account: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {"ok": False, "reason": "No fixed-income broker adapter configured; scan-only."}

