"""System-wide status reporting across repositories."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from adi.engine.artifact_store import ArtifactStore
from adi.engine.config_loader import ConfigLoader


class SystemService:
    """Aggregate high-level ADI status across repos/specs/tasks/runs."""

    def __init__(
        self,
        config_loader: ConfigLoader | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.config_loader = config_loader or ConfigLoader()
        self.artifact_store = artifact_store or ArtifactStore()

    def status(self) -> dict[str, Any]:
        repos = self.config_loader.load_repos_registry()
        repo_items: list[dict[str, Any]] = []
        spec_counts: dict[str, int] = {}
        task_counts: dict[str, int] = {}

        for entry in repos:
            repo_id = str(entry.get("id", ""))
            root = Path(str(entry.get("root", ""))).expanduser().resolve()
            available = root.exists() and root.is_dir()
            repo_items.append(
                {
                    "id": repo_id,
                    "name": entry.get("name"),
                    "available": available,
                    "root": str(root),
                }
            )

            specs_dir = self.config_loader.repos_dir / repo_id / "specs"
            for path in specs_dir.glob("*.md"):
                status = str(self.artifact_store.read(path).frontmatter.get("status", "unknown"))
                spec_counts[status] = spec_counts.get(status, 0) + 1

            tasks_dir = self.config_loader.repos_dir / repo_id / "tasks"
            for path in tasks_dir.glob("*.md"):
                status = str(self.artifact_store.read(path).frontmatter.get("status", "unknown"))
                task_counts[status] = task_counts.get(status, 0) + 1

        runs_total = len([path for path in self.config_loader.runs_dir.glob("*") if path.is_dir()])
        repos_available = sum(1 for item in repo_items if item["available"])
        specs_total = sum(spec_counts.values())
        tasks_total = sum(task_counts.values())

        return {
            "summary": {
                "repos_total": len(repo_items),
                "repos_available": repos_available,
                "repos_unavailable": len(repo_items) - repos_available,
                "specs_total": specs_total,
                "tasks_total": tasks_total,
                "runs_total": runs_total,
            },
            "repos": repo_items,
            "specs": {
                "total": specs_total,
                "by_status": spec_counts,
            },
            "tasks": {
                "total": tasks_total,
                "by_status": task_counts,
            },
            "runs": {
                "total": runs_total,
            },
        }
