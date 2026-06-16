from __future__ import annotations

from typing import Any, Dict


class ProofCenterFacade:
    def __init__(self, settings: Dict[str, Any], paper_proof: Dict[str, Any] | None = None):
        self.settings = settings
        self.paper_proof = paper_proof or {}

    def live_allowed(self) -> bool:
        if not self.settings.get("PMO_REQUIRE_PAPER_PROOF_FOR_LIVE_EXECUTOR", True):
            return True
        return bool(self.paper_proof.get("ready_to_unlock_live"))

    def summary(self) -> Dict[str, Any]:
        return {"live_allowed": self.live_allowed(), "paper_proof": self.paper_proof}
