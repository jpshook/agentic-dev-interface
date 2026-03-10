"""Policy decision model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class PolicyDecision:
    """Structured policy evaluation result."""

    action: str
    reasons: list[str] = field(default_factory=list)
