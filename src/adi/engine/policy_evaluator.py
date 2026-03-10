"""Policy evaluator."""

from __future__ import annotations

from adi.models.policy import PolicyDecision


_SIZE_RANK = {
    "small": 1,
    "medium": 2,
    "large": 3,
}

_RISK_RANK = {
    "low": 1,
    "medium": 2,
    "high": 3,
}


class PolicyEvaluator:
    """Deterministic policy evaluation for task execution safety."""

    def evaluate(
        self,
        *,
        risk: str,
        size: str,
        dependencies_satisfied: bool,
        touches_restricted_area: bool,
        auto_max_risk: str = "low",
        auto_max_size: str = "small",
    ) -> PolicyDecision:
        reasons: list[str] = []

        if touches_restricted_area:
            return PolicyDecision(
                action="deny",
                reasons=["Task touches restricted area"],
                metadata={"risk": risk, "size": size},
            )

        if not dependencies_satisfied:
            return PolicyDecision(
                action="require_human_input",
                reasons=["Dependencies are not satisfied"],
                metadata={"risk": risk, "size": size},
            )

        size_rank = _SIZE_RANK.get(size, 999)
        risk_rank = _RISK_RANK.get(risk, 999)
        auto_size_rank = _SIZE_RANK.get(auto_max_size, 1)
        auto_risk_rank = _RISK_RANK.get(auto_max_risk, 1)

        if size_rank <= auto_size_rank and risk_rank <= auto_risk_rank:
            reasons.append("Task is within automatic execution thresholds")
            return PolicyDecision(action="auto_execute", reasons=reasons, metadata={"risk": risk, "size": size})

        reasons.append("Task exceeds automatic execution thresholds")
        return PolicyDecision(action="require_approval", reasons=reasons, metadata={"risk": risk, "size": size})
