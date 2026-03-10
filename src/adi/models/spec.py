"""Spec models and lifecycle transitions."""

from __future__ import annotations

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

SPEC_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"analyzed", "blocked"},
    "analyzed": {"decomposed", "blocked"},
    "decomposed": {"approved", "blocked"},
    "approved": {"in_progress", "blocked"},
    "in_progress": {"completed", "blocked"},
    "completed": set(),
    "blocked": {"draft", "analyzed", "decomposed", "approved", "in_progress"},
}


def can_transition_spec(current: str, target: str) -> bool:
    """Return whether a spec lifecycle transition is allowed."""
    return target in SPEC_TRANSITIONS.get(current, set())
