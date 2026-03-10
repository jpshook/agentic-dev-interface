"""Prompt builder for agent roles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from adi.engine.config_loader import ConfigLoader
from adi.engine.yaml_utils import dump_yaml


class PromptBuilder:
    """Assemble role prompts from templates + runtime context."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or ConfigLoader()

    def build(
        self,
        *,
        role: str,
        repo_id: str,
        run_id: str,
        attempt: int,
        worktree_path: Path,
        task_frontmatter: dict[str, Any],
        task_body: str,
        repo_frontmatter: dict[str, Any],
        spec_context: str,
        retry_context: str,
    ) -> str:
        template = self._load_template(role)

        values = {
            "task_id": str(task_frontmatter.get("id", "")),
            "repo_id": repo_id,
            "run_id": run_id,
            "attempt": str(attempt),
            "worktree_path": str(worktree_path),
            "task_frontmatter": dump_yaml(task_frontmatter).strip(),
            "task_body": task_body.strip() or "(empty)",
            "acceptance_checks": ", ".join(task_frontmatter.get("acceptance_checks", [])) or "(none)",
            "repo_commands": dump_yaml(repo_frontmatter.get("commands", {})).strip() or "(none)",
            "spec_context": spec_context.strip() or "(none)",
            "retry_context": retry_context.strip() or "(none)",
        }

        prompt = template
        for key, value in values.items():
            prompt = prompt.replace(f"{{{{{key}}}}}", value)
        return prompt

    def _load_template(self, role: str) -> str:
        # Repo-local ADI template overrides built-ins.
        override = self.config_loader.templates_dir / "prompts" / f"{role}.md"
        if override.exists():
            return override.read_text(encoding="utf-8")

        builtin = Path(__file__).resolve().parent.parent / "templates" / "prompts" / f"{role}.md"
        if not builtin.exists():
            raise ValueError(f"Missing prompt template for role '{role}'")
        return builtin.read_text(encoding="utf-8")
