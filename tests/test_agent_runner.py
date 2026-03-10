from pathlib import Path

from adi.engine.agent_runner import AgentRunner
from adi.engine.config_loader import ConfigLoader
from adi.engine.yaml_utils import dump_yaml


def test_agent_runner_stub_runtime(tmp_path: Path, monkeypatch) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    loader = ConfigLoader(adi_home=adi_home)
    loader.ensure_initialized()

    runner = AgentRunner(config_loader=loader)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir(parents=True)

    result = runner.run(
        role="implementer",
        repo_id="demo-repo",
        prompt="hello",
        prompt_path=run_dir / "prompt.md",
        worktree_path=worktree,
        run_dir=run_dir,
        attempt=1,
    )

    assert result.success is True
    assert result.runtime == "stub"


def test_agent_runner_shell_runtime_executes_command(tmp_path: Path, monkeypatch) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    loader = ConfigLoader(adi_home=adi_home)
    loader.ensure_initialized()

    models_path = loader.config_dir / "models.yaml"
    models_path.write_text(
        dump_yaml(
            {
                "models": {
                    "implementer": {
                        "runtime": "shell",
                        "command": "sh -c 'echo changed > changed.txt'",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    runner = AgentRunner(config_loader=loader)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir(parents=True)

    result = runner.run(
        role="implementer",
        repo_id="demo-repo",
        prompt="hello",
        prompt_path=run_dir / "prompt.md",
        worktree_path=worktree,
        run_dir=run_dir,
        attempt=1,
    )

    assert result.success is True
    assert result.runtime == "shell"
    assert (worktree / "changed.txt").exists()
