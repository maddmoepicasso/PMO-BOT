"""Placeholder futures capability map.

No futures broker is configured, so everything remains scan-only.
"""
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
account_permission_requirements = {"FUTURES": ["futures_approval", "margin_approval"]}
data_feed_requirements = {"FUTURES": ["futures_data_feed"]}
known_limitations = ["No futures broker adapter is configured. Futures stay scan-only."]
CAPABILITIES = {k: v for k, v in globals().items() if k in {
    "supported_asset_classes", "supported_order_types_by_asset_class", "supported_time_in_force",
    "supports_fractional", "supports_shorting", "supports_options", "supports_futures",
    "supports_forex", "supports_crypto", "supports_bonds", "supports_mutual_funds",
    "paper_supported", "live_supported", "account_permission_requirements",
    "data_feed_requirements", "known_limitations",
}}
CAPABILITIES["broker"] = "futures"


def validate_order_capability(order_request: Dict[str, Any], account: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {"ok": False, "reason": "No futures broker adapter configured; scan-only."}

