from pathlib import Path

from adi.engine.config_loader import ConfigLoader
from adi.engine.prompt_builder import PromptBuilder


def test_prompt_builder_includes_context(tmp_path: Path, monkeypatch) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    loader = ConfigLoader(adi_home=adi_home)
    loader.ensure_initialized()
    builder = PromptBuilder(config_loader=loader)

    prompt = builder.build(
        role="implementer",
        repo_id="demo-repo",
        run_id="run-1",
        attempt=2,
        worktree_path=tmp_path / "worktree",
        task_frontmatter={
            "id": "TK-001",
            "acceptance_checks": ["test", "lint"],
        },
        task_body="# Body\n",
        repo_frontmatter={"commands": {"test": "pytest -q"}},
        spec_context="spec context",
        retry_context="retry details",
    )

    assert "Task ID: TK-001" in prompt
    assert "Run ID: run-1" in prompt
    assert "Attempt: 2" in prompt
    assert "retry details" in prompt
    assert "spec context" in prompt


def test_prompt_builder_respects_template_override(tmp_path: Path, monkeypatch) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    loader = ConfigLoader(adi_home=adi_home)
    loader.ensure_initialized()
    override = loader.templates_dir / "prompts" / "implementer.md"
    override.parent.mkdir(parents=True, exist_ok=True)
    override.write_text("override {{task_id}}", encoding="utf-8")

    builder = PromptBuilder(config_loader=loader)
    prompt = builder.build(
        role="implementer",
        repo_id="demo-repo",
        run_id="run-1",
        attempt=1,
        worktree_path=tmp_path / "worktree",
        task_frontmatter={"id": "TK-009", "acceptance_checks": []},
        task_body="",
        repo_frontmatter={"commands": {}},
        spec_context="",
        retry_context="",
    )

    assert prompt == "override TK-009"
