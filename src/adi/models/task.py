"""Task models, schema validation, and lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TASK_REQUIRED_FIELDS = {
    "id",
    "title",
    "repo_id",
    "status",
    "priority",
    "size",
    "risk",
    "created_at",
    "updated_at",
    "depends_on",
    "acceptance_checks",
}

TASK_STATES = {
    "proposed",
    "approved",
    "in_progress",
    "pending_verification",
    "completed",
    "failed",
    "blocked",
}

TASK_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"approved", "blocked"},
    "approved": {"in_progress", "blocked"},
    "in_progress": {"pending_verification", "completed", "failed", "blocked"},
    "pending_verification": {"completed", "failed", "blocked"},
    "completed": set(),
    "failed": set(),
    "blocked": {"approved"},
}


@dataclass(slots=True)
class TaskArtifact:
    """Typed representation of task.md frontmatter."""

    id: str
    title: str
    repo_id: str
    status: str
    priority: str
    size: str
    risk: str
    created_at: str
    updated_at: str
    depends_on: list[str] = field(default_factory=list)
    acceptance_checks: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_frontmatter(cls, frontmatter: dict[str, Any]) -> "TaskArtifact":
        validate_task_frontmatter(frontmatter)
        known = {k: frontmatter[k] for k in TASK_REQUIRED_FIELDS}
        extras = {k: v for k, v in frontmatter.items() if k not in TASK_REQUIRED_FIELDS}
        return cls(
            id=str(known["id"]),
            title=str(known["title"]),
            repo_id=str(known["repo_id"]),
            status=str(known["status"]),
            priority=str(known["priority"]),
            size=str(known["size"]),
            risk=str(known["risk"]),
            created_at=str(known["created_at"]),
            updated_at=str(known["updated_at"]),
            depends_on=[str(item) for item in known["depends_on"]],
            acceptance_checks=[str(item) for item in known["acceptance_checks"]],
            extras=extras,
        )


def validate_task_frontmatter(frontmatter: dict[str, Any]) -> None:
    """Validate required task schema fields and basic types."""
    missing = TASK_REQUIRED_FIELDS.difference(frontmatter)
    if missing:
        fields = ", ".join(sorted(missing))
        raise ValueError(f"Missing required task fields: {fields}")

    status = str(frontmatter["status"])
    if status not in TASK_STATES:
        allowed = ", ".join(sorted(TASK_STATES))
        raise ValueError(f"Invalid task status '{status}'. Allowed: {allowed}")

    depends_on = frontmatter["depends_on"]
    if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
        raise ValueError("Task field 'depends_on' must be a list of strings")

    acceptance_checks = frontmatter["acceptance_checks"]
    if not isinstance(acceptance_checks, list) or not all(
        isinstance(item, str) for item in acceptance_checks
    ):
        raise ValueError("Task field 'acceptance_checks' must be a list of strings")


def can_transition_task(current: str, target: str) -> bool:
    """Return whether a task lifecycle transition is allowed."""
    return target in TASK_TRANSITIONS.get(current, set())


def assert_task_transition(current: str, target: str) -> None:
    """Raise if transition is not allowed."""
    if not can_transition_task(current, target):
        raise ValueError(f"Invalid task transition: {current} -> {target}")
