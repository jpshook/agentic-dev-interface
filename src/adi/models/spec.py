"""Spec models, schema validation, and lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SPEC_REQUIRED_FIELDS = {
    "id",
    "title",
    "repo_id",
    "status",
    "priority",
    "created_at",
    "updated_at",
    "execution_mode",
}

SPEC_STATES = {
    "draft",
    "analyzed",
    "decomposed",
    "approved",
    "in_progress",
    "completed",
    "blocked",
}

SPEC_EXECUTION_MODES = {
    "manual",
    "approval_required",
    "auto_safe",
}

SPEC_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"analyzed", "blocked"},
    "analyzed": {"decomposed", "blocked"},
    "decomposed": {"approved", "blocked"},
    "approved": {"in_progress", "blocked"},
    "in_progress": {"completed", "blocked"},
    "completed": set(),
    "blocked": {"draft", "analyzed", "decomposed", "approved", "in_progress"},
}


@dataclass(slots=True)
class SpecArtifact:
    """Typed representation of spec.md frontmatter."""

    id: str
    title: str
    repo_id: str
    status: str
    priority: str
    created_at: str
    updated_at: str
    execution_mode: str
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_frontmatter(cls, frontmatter: dict[str, Any]) -> "SpecArtifact":
        validate_spec_frontmatter(frontmatter)
        known = {k: frontmatter[k] for k in SPEC_REQUIRED_FIELDS}
        extras = {k: v for k, v in frontmatter.items() if k not in SPEC_REQUIRED_FIELDS}
        return cls(
            id=str(known["id"]),
            title=str(known["title"]),
            repo_id=str(known["repo_id"]),
            status=str(known["status"]),
            priority=str(known["priority"]),
            created_at=str(known["created_at"]),
            updated_at=str(known["updated_at"]),
            execution_mode=str(known["execution_mode"]),
            extras=extras,
        )


def validate_spec_frontmatter(frontmatter: dict[str, Any]) -> None:
    """Validate required spec schema fields and supported values."""
    missing = SPEC_REQUIRED_FIELDS.difference(frontmatter)
    if missing:
        fields = ", ".join(sorted(missing))
        raise ValueError(f"Missing required spec fields: {fields}")

    status = str(frontmatter["status"])
    if status not in SPEC_STATES:
        allowed = ", ".join(sorted(SPEC_STATES))
        raise ValueError(f"Invalid spec status '{status}'. Allowed: {allowed}")

    execution_mode = str(frontmatter["execution_mode"])
    if execution_mode not in SPEC_EXECUTION_MODES:
        allowed_modes = ", ".join(sorted(SPEC_EXECUTION_MODES))
        raise ValueError(
            f"Invalid spec execution_mode '{execution_mode}'. Allowed: {allowed_modes}"
        )


def can_transition_spec(current: str, target: str) -> bool:
    """Return whether a spec lifecycle transition is allowed."""
    return target in SPEC_TRANSITIONS.get(current, set())


def assert_spec_transition(current: str, target: str) -> None:
    """Raise if transition is not allowed."""
    if not can_transition_spec(current, target):
        raise ValueError(f"Invalid spec transition: {current} -> {target}")
