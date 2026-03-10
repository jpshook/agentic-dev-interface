"""Git worktree helpers for task execution."""

from __future__ import annotations

from pathlib import Path


class WorktreeManager:
    """Minimal placeholder implementation for later phases."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def path_for_task(self, repo_id: str, task_id: str) -> Path:
        return self.root / repo_id / task_id
