import subprocess
from pathlib import Path

from adi.cli.main import main
from adi.engine.artifact_store import ArtifactStore
from adi.engine.config_loader import ConfigLoader
from adi.engine.yaml_utils import dump_yaml, load_yaml


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)
    (path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "pyproject.toml"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        check=True,
        capture_output=True,
    )


def test_spec_cli_analyze_decompose_approve_status(tmp_path: Path, monkeypatch, capsys) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    repo_path = tmp_path / "SpecRepo"
    _init_git_repo(repo_path)

    assert main(["repo", "init", "--path", str(repo_path)]) == 0
    repo_id = load_yaml(capsys.readouterr().out)["repo"]["id"]

    assert main(["repo", "explore", "--repo", repo_id]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "spec",
                "create",
                "--repo",
                repo_id,
                "--title",
                "API validation spec",
                "--id",
                "SP-001",
                "--execution-mode",
                "manual",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["spec", "analyze", "SP-001"]) == 0
    analyze = load_yaml(capsys.readouterr().out)
    assert analyze["status"] == "analyzed"

    assert main(["spec", "decompose", "SP-001"]) == 0
    decompose = load_yaml(capsys.readouterr().out)
    assert decompose["status"] == "decomposed"
    assert decompose["generated_tasks"]

    assert main(["spec", "status", "SP-001"]) == 0
    status_before = load_yaml(capsys.readouterr().out)
    assert status_before["spec"]["status"] == "decomposed"
    assert status_before["linked_tasks"]["count"] == len(decompose["generated_tasks"])

    assert main(["spec", "approve", "SP-001"]) == 0
    approve = load_yaml(capsys.readouterr().out)
    assert approve["status"] == "approved"

    assert main(["spec", "status", "SP-001"]) == 0
    status_after = load_yaml(capsys.readouterr().out)
    assert status_after["spec"]["status"] == "approved"


def test_spec_run_auto_safe_hands_off_to_backlog(tmp_path: Path, monkeypatch, capsys) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    repo_path = tmp_path / "AutoRepo"
    _init_git_repo(repo_path)

    assert main(["repo", "init", "--path", str(repo_path)]) == 0
    repo_id = load_yaml(capsys.readouterr().out)["repo"]["id"]

    loader = ConfigLoader(adi_home=adi_home)
    loader.ensure_initialized()
    (loader.config_dir / "adi.yaml").write_text(
        dump_yaml(
            {
                "execution": {
                    "worktree_root": str(tmp_path / "worktrees"),
                    "default_timeout_seconds": 120,
                    "verification_fix_cycles": 1,
                    "total_task_attempts": 1,
                    "max_active_runs_global": 2,
                    "max_active_runs_per_repo": 2,
                }
            }
        ),
        encoding="utf-8",
    )
    (loader.config_dir / "models.yaml").write_text(
        dump_yaml({"models": {"implementer": {"runtime": "stub"}}}),
        encoding="utf-8",
    )

    assert main(["repo", "explore", "--repo", repo_id]) == 0
    capsys.readouterr()

    store = ArtifactStore()
    repo_md_path = adi_home / "repos" / repo_id / "repo.md"
    store.update(repo_md_path, frontmatter_updates={"commands": {"test": "python3 -c 'print(1)'"}})

    assert (
        main(
            [
                "spec",
                "create",
                "--repo",
                repo_id,
                "--title",
                "Auto safe spec",
                "--id",
                "SP-002",
                "--execution-mode",
                "auto_safe",
            ]
        )
        == 0
    )
    capsys.readouterr()

    spec_path = adi_home / "repos" / repo_id / "specs" / "SP-002.md"
    doc = store.read(spec_path)
    doc.body += "\n## Acceptance Criteria\n\n- Implement API input parsing\n- Add tests for API input parsing\n"
    store.write(spec_path, doc)

    assert main(["spec", "run", "SP-002", "--max-tasks", "3"]) == 0
    run_payload = load_yaml(capsys.readouterr().out)

    assert run_payload["backlog_started"] is True
    assert run_payload["status"] in {"in_progress", "completed"}
    assert run_payload["backlog_run"]["dispatched_tasks"] >= 1

    assert main(["spec", "status", "SP-002"]) == 0
    status = load_yaml(capsys.readouterr().out)
    assert status["linked_tasks"]["count"] >= 1
    assert status["spec"]["status"] in {"in_progress", "completed", "blocked"}
