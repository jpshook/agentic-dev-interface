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


def test_repos_list_and_system_status(tmp_path: Path, monkeypatch, capsys) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    repo_a = tmp_path / "web-app"
    repo_b = tmp_path / "api-service"
    _init_git_repo(repo_a)
    _init_git_repo(repo_b)

    assert main(["repo", "init", "--path", str(repo_a)]) == 0
    repo_a_id = load_yaml(capsys.readouterr().out)["repo"]["id"]
    assert main(["repo", "init", "--path", str(repo_b)]) == 0
    repo_b_id = load_yaml(capsys.readouterr().out)["repo"]["id"]

    assert (
        main(
            [
                "spec",
                "create",
                "--repo",
                repo_a_id,
                "--title",
                "System status spec",
                "--id",
                "SP-SYS",
                "--execution-mode",
                "manual",
            ]
        )
        == 0
    )
    capsys.readouterr()

    store = ArtifactStore()
    task_path = adi_home / "repos" / repo_b_id / "tasks" / "TK-SYS-001.md"
    store.write(
        task_path,
        ArtifactDocument(
            frontmatter={
                "id": "TK-SYS-001",
                "title": "System status task",
                "repo_id": repo_b_id,
                "status": "approved",
                "priority": "medium",
                "size": "small",
                "risk": "low",
                "created_at": "2026-03-10T00:00:00+00:00",
                "updated_at": "2026-03-10T00:00:00+00:00",
                "depends_on": [],
                "acceptance_checks": ["test"],
            },
            body="# TK-SYS-001\n",
        ),
    )

    assert main(["repos", "list"]) == 0
    repos_payload = load_yaml(capsys.readouterr().out)
    assert repos_payload["summary"]["total"] == 2
    assert repos_payload["summary"]["available"] == 2

    assert main(["system", "status"]) == 0
    status_payload = load_yaml(capsys.readouterr().out)
    assert status_payload["summary"]["repos_total"] == 2
    assert status_payload["summary"]["repos_available"] == 2
    assert status_payload["summary"]["specs_total"] >= 1
    assert status_payload["summary"]["tasks_total"] >= 1
