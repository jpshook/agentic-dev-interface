"""Artifact persistence with frontmatter validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .frontmatter import parse_frontmatter_markdown, render_frontmatter_markdown

Validator = Callable[[dict[str, Any]], Any]


@dataclass(slots=True)
class ArtifactDocument:
    """In-memory artifact document."""

    frontmatter: dict[str, Any]
    body: str


class ArtifactStore:
    """Read/write markdown artifacts with YAML frontmatter."""

    def read(self, path: Path) -> ArtifactDocument:
        text = path.read_text(encoding="utf-8")
        parsed = parse_frontmatter_markdown(text)
        return ArtifactDocument(frontmatter=parsed.frontmatter, body=parsed.body)

    def write(
        self,
        path: Path,
        document: ArtifactDocument,
        validator: Validator | None = None,
    ) -> None:
        if validator is not None:
            validator(document.frontmatter)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = render_frontmatter_markdown(document.frontmatter, document.body)
        path.write_text(text, encoding="utf-8")

    def update(
        self,
        path: Path,
        frontmatter_updates: dict[str, Any] | None = None,
        body: str | None = None,
        validator: Validator | None = None,
    ) -> ArtifactDocument:
        current = self.read(path)
        updated_frontmatter = dict(current.frontmatter)
        if frontmatter_updates:
            updated_frontmatter.update(frontmatter_updates)
        updated_body = current.body if body is None else body
        updated_doc = ArtifactDocument(frontmatter=updated_frontmatter, body=updated_body)
        self.write(path, updated_doc, validator=validator)
        return updated_doc
