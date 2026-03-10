import subprocess
from pathlib import Path

from adi.cli.main import main
from adi.engine.artifact_store import ArtifactDocument, ArtifactStore
from adi.engine.yaml_utils import load_yaml


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True)
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
    depends_on: list[str] | None = None,
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
                "depends_on": depends_on or [],
                "acceptance_checks": ["test"],
            },
            body=f"# {task_id}\n",
        ),
    )


def test_backlog_show_counts_by_status(tmp_path: Path, monkeypatch, capsys) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    repo_path = tmp_path / "DemoRepo"
    _init_git_repo(repo_path)

    assert main(["repo", "init", "--path", str(repo_path)]) == 0
    repo_id = load_yaml(capsys.readouterr().out)["repo"]["id"]

    _write_task(adi_home, repo_id, "TK-READY", "approved")
    _write_task(adi_home, repo_id, "TK-BLOCKED", "approved", depends_on=["TK-NEEDS"])
    _write_task(adi_home, repo_id, "TK-RUNNING", "in_progress")
    _write_task(adi_home, repo_id, "TK-COMPLETE", "completed")
    _write_task(adi_home, repo_id, "TK-FAILED", "failed")
    _write_task(adi_home, repo_id, "TK-PENDING", "proposed")

    assert main(["backlog", "show", "--repo", repo_id]) == 0
    payload = load_yaml(capsys.readouterr().out)

    assert payload["summary"]["ready"] == 1
    assert payload["summary"]["blocked"] == 1
    assert payload["summary"]["running"] == 1
    assert payload["summary"]["completed"] == 1
    assert payload["summary"]["failed"] == 1
    assert payload["summary"]["pending"] == 1
