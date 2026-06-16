from __future__ import annotations

from typing import Any, Dict


class ExecutionGuardFacade:
    """Thin v206 adapter for PMO's existing gated executor.

    The behavior stays inside PMOBot while v206 moves callers toward a clean module boundary.
    """
    def __init__(self, bot: Any):
        self.bot = bot

    def status(self) -> Dict[str, Any]:
        return self.bot.executor_status()

    def build_trade_plan(self, decision: Dict[str, Any], payload: Dict[str, Any], account: Dict[str, Any] | None = None, record: bool = False) -> Dict[str, Any]:
        return self.bot.build_trade_plan(decision, payload, account=account, record=record)

    def submit(self, decision: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        return self.bot.submit_order_from_decision(decision, payload)
