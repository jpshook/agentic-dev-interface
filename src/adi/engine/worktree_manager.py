"""Git worktree helpers for task execution."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


class WorktreeManager:
    """Create per-task git worktrees and branches."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()

    def path_for_task(self, repo_id: str, task_id: str) -> Path:
        return self.root / repo_id / task_id

    def branch_for_task(self, task_id: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9._/-]+", "-", task_id).strip("-")
        normalized = normalized or "task"
        return f"adi/{normalized}"

    def ensure_worktree(
        self,
        repo_root: Path,
        repo_id: str,
        task_id: str,
        base_branch: str,
    ) -> tuple[Path, str]:
        repo_root = repo_root.resolve()
        worktree_path = self.path_for_task(repo_id, task_id)
        branch = self.branch_for_task(task_id)

        if worktree_path.exists() and (worktree_path / ".git").exists():
            return worktree_path, branch

        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._branch_exists(repo_root, branch):
            self._git(repo_root, ["branch", branch, base_branch])
        self._git(repo_root, ["worktree", "add", str(worktree_path), branch])
        return worktree_path, branch

    def _branch_exists(self, repo_root: Path, branch: str) -> bool:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def _git(self, repo_root: Path, args: list[str]) -> None:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or "unknown git error"
            raise RuntimeError(f"git {' '.join(args)} failed: {stderr}")
