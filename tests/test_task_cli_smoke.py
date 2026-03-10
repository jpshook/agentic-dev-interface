import subprocess
from pathlib import Path

from adi.cli.main import main
from adi.engine.artifact_store import ArtifactDocument, ArtifactStore
from adi.engine.config_loader import ConfigLoader
from adi.engine.yaml_utils import dump_yaml, load_yaml


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)
    (path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    tests_dir = path / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_sample.py").write_text(
        "def test_sample():\n    assert True\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
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


def _write_task(
    adi_home: Path,
    repo_id: str,
    task_id: str,
    status: str,
    acceptance_checks: list[str],
) -> None:
    store = ArtifactStore()
    task_path = adi_home / "repos" / repo_id / "tasks" / f"{task_id}.md"
    store.write(
        task_path,
        ArtifactDocument(
            frontmatter={
                "id": task_id,
                "title": f"Task {task_id}",
                "repo_id": repo_id,
                "status": status,
                "priority": "medium",
                "size": "small",
                "risk": "low",
                "created_at": "2026-03-10T00:00:00+00:00",
                "updated_at": "2026-03-10T00:00:00+00:00",
                "depends_on": [],
                "acceptance_checks": acceptance_checks,
            },
            body=f"# {task_id}\n\nDeterministic task.\n",
        ),
    )


def test_task_cli_run_and_verify(tmp_path: Path, monkeypatch, capsys) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    repo_path = tmp_path / "DemoRepo"
    _init_git_repo(repo_path)

    assert main(["repo", "init", "--path", str(repo_path)]) == 0
    init_payload = load_yaml(capsys.readouterr().out)
    repo_id = init_payload["repo"]["id"]

    loader = ConfigLoader(adi_home=adi_home)
    loader.ensure_initialized()
    (loader.config_dir / "adi.yaml").write_text(
        dump_yaml(
            {
                "execution": {
                    "worktree_root": str(tmp_path / "worktrees"),
                    "default_timeout_seconds": 120,
                }
            }
        ),
        encoding="utf-8",
    )

    assert main(["repo", "explore", "--repo", repo_id]) == 0
    capsys.readouterr()

    _write_task(adi_home, repo_id, "TK-001", "proposed", ["test"])
    _write_task(adi_home, repo_id, "TK-002", "approved", ["test"])

    assert main(["task", "list", "--repo", repo_id]) == 0
    list_payload = load_yaml(capsys.readouterr().out)
    assert len(list_payload["tasks"]) == 2

    assert main(["task", "approve", "TK-001"]) == 0
    approve_payload = load_yaml(capsys.readouterr().out)
    assert approve_payload["status"] == "approved"

    assert main(["task", "run", "TK-001"]) == 0
    run_payload = load_yaml(capsys.readouterr().out)
    assert run_payload["status"] == "completed"

    assert main(["task", "show", "TK-001"]) == 0
    show_payload = load_yaml(capsys.readouterr().out)
    assert show_payload["task"]["frontmatter"]["status"] == "completed"

    assert main(["task", "verify", "TK-002"]) == 0
    verify_payload = load_yaml(capsys.readouterr().out)
    assert verify_payload["status"] == "completed"

    worktree_path = Path(run_payload["worktree"])
    assert worktree_path.exists()

    runs_dir = adi_home / "runs"
    run_dirs = [path for path in runs_dir.iterdir() if path.is_dir()]
    assert len(run_dirs) >= 2
    assert any((path / "metadata.yaml").exists() for path in run_dirs)
    assert any((path / "verification.yaml").exists() for path in run_dirs)
