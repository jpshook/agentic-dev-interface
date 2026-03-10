"""Repository artifact models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REPO_REQUIRED_FIELDS = {
    "id",
    "name",
    "root",
    "default_branch",
    "status",
    "commands",
}


@dataclass(slots=True)
class RepoArtifact:
    """Typed representation of repo.md frontmatter."""

    id: str
    name: str
    root: str
    default_branch: str
    status: str
    commands: dict[str, str] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_frontmatter(cls, frontmatter: dict[str, Any]) -> "RepoArtifact":
        missing = REPO_REQUIRED_FIELDS.difference(frontmatter)
        if missing:
            missing_fields = ", ".join(sorted(missing))
            raise ValueError(f"Missing required repo fields: {missing_fields}")

        known = {k: frontmatter[k] for k in REPO_REQUIRED_FIELDS}
        extras = {k: v for k, v in frontmatter.items() if k not in REPO_REQUIRED_FIELDS}
        return cls(
            id=str(known["id"]),
            name=str(known["name"]),
            root=str(known["root"]),
            default_branch=str(known["default_branch"]),
            status=str(known["status"]),
            commands=dict(known["commands"]),
            extras=extras,
        )
