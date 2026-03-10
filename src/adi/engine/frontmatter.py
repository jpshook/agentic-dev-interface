"""Markdown + YAML frontmatter parser/writer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .yaml_utils import dump_yaml, load_yaml


@dataclass(slots=True)
class ParsedFrontmatter:
    """Parsed markdown document with YAML frontmatter."""

    frontmatter: dict[str, Any]
    body: str


def parse_frontmatter_markdown(text: str) -> ParsedFrontmatter:
    """Parse markdown with optional YAML frontmatter.

    Expected format:
      ---
      key: value
      ---
      markdown body
    """
    if not text.startswith("---\n"):
        return ParsedFrontmatter(frontmatter={}, body=text)

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return ParsedFrontmatter(frontmatter={}, body=text)

    closing_index = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = idx
            break

    if closing_index is None:
        return ParsedFrontmatter(frontmatter={}, body=text)

    raw_frontmatter = "".join(lines[1:closing_index])
    body = "".join(lines[closing_index + 1 :])

    parsed = load_yaml(raw_frontmatter) if raw_frontmatter.strip() else {}
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        raise ValueError("Frontmatter must parse to a mapping")

    return ParsedFrontmatter(frontmatter=parsed, body=body)


def render_frontmatter_markdown(frontmatter: dict[str, Any], body: str) -> str:
    """Render frontmatter + markdown body."""
    normalized_body = body
    yaml_text = dump_yaml(frontmatter).strip()
    if yaml_text:
        return f"---\n{yaml_text}\n---\n{normalized_body}"
    return normalized_body
