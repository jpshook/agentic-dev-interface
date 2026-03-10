"""Run models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC


@dataclass(slots=True)
class RunRecord:
    """Durable run metadata."""

    id: str
    task_id: str
    repo_id: str
    created_at: str

    @classmethod
    def create(cls, run_id: str, task_id: str, repo_id: str) -> "RunRecord":
        return cls(
            id=run_id,
            task_id=task_id,
            repo_id=repo_id,
            created_at=datetime.now(UTC).isoformat(),
        )
