"""Repository registry services for multi-repo orchestration visibility."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from adi.engine.artifact_store import ArtifactStore
from adi.engine.config_loader import ConfigLoader


class ReposService:
    """Read-only accessors for registered repositories."""

    def __init__(
        self,
        config_loader: ConfigLoader | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.config_loader = config_loader or ConfigLoader()
        self.artifact_store = artifact_store or ArtifactStore()

    def list_repos(self) -> dict[str, Any]:
        repos = self.config_loader.load_repos_registry()
        items: list[dict[str, Any]] = []

        for entry in repos:
            repo_id = str(entry.get("id", ""))
            root = Path(str(entry.get("root", ""))).expanduser().resolve()
            repo_md = self.config_loader.repos_dir / repo_id / "repo.md"

            language = None
            stack: list[str] = []
            if repo_md.exists():
                frontmatter = self.artifact_store.read(repo_md).frontmatter
                language = frontmatter.get("language")
                stack_raw = frontmatter.get("stack", [])
                if isinstance(stack_raw, list):
                    stack = [str(item) for item in stack_raw]

            items.append(
                {
                    "id": repo_id,
                    "name": entry.get("name"),
                    "root": str(root),
                    "default_branch": entry.get("default_branch"),
                    "status": entry.get("status", "active"),
                    "available": root.exists() and root.is_dir(),
                    "language": language,
                    "stack": stack,
                }
            )

        available = sum(1 for item in items if item["available"])
        return {
            "summary": {
                "total": len(items),
                "available": available,
                "unavailable": len(items) - available,
            },
            "repos": items,
        }
