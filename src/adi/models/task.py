"""Task models and lifecycle transitions."""

from __future__ import annotations

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

TASK_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"approved", "blocked", "skipped"},
    "approved": {"in_progress", "blocked", "skipped"},
    "in_progress": {"pending_verification", "failed", "needs_human", "blocked"},
    "pending_verification": {"completed", "failed", "needs_human"},
    "completed": set(),
    "blocked": {"proposed", "approved"},
    "needs_human": {"approved", "blocked", "skipped"},
    "failed": {"approved", "blocked", "skipped"},
    "skipped": set(),
}


def can_transition_task(current: str, target: str) -> bool:
    """Return whether a task lifecycle transition is allowed."""
    return target in TASK_TRANSITIONS.get(current, set())
