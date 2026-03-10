"""Run directory manager."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


class RunManager:
    """Create deterministic run ids and directories."""

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root

    def create_run_dir(self, repo_id: str, task_id: str) -> Path:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_dir = self.runs_root / f"{run_id}-{repo_id}-{task_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir
