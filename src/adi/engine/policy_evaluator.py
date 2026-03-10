"""Policy evaluator."""

from __future__ import annotations

from adi.models.policy import PolicyDecision


class PolicyEvaluator:
    """Deterministic default policy evaluation."""

    def evaluate(self, risk: str, size: str, touches_restricted_area: bool) -> PolicyDecision:
        if touches_restricted_area:
            return PolicyDecision(action="deny", reasons=["Task touches restricted area"])
        if risk == "low" and size == "small":
            return PolicyDecision(action="auto_execute", reasons=["Low risk and small scope"])
        return PolicyDecision(action="require_approval", reasons=["Requires human review"])
