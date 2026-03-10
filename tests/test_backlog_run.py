import subprocess
import time
from pathlib import Path

from adi.cli.main import main
from adi.engine.artifact_store import ArtifactDocument, ArtifactStore
from adi.engine.config_loader import ConfigLoader
from adi.engine.yaml_utils import dump_yaml, load_yaml
from adi.services.backlog_service import BacklogService


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


class _FakeTaskService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_task(self, task_id: str) -> dict[str, object]:
        self.calls.append(task_id)
        time.sleep(0.2)
        return {
            "task_id": task_id,
            "status": "completed",
            "run_id": f"run-{task_id}",
        }


def _write_task(
    adi_home: Path,
    repo_id: str,
    task_id: str,
    *,
    status: str = "approved",
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


def test_backlog_run_respects_dependencies_and_runs_phase4_tasks(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    repo_path = tmp_path / "DemoRepo"
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
                    "max_active_runs_global": 1,
                    "max_active_runs_per_repo": 1,
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

    repo_md_path = adi_home / "repos" / repo_id / "repo.md"
    store = ArtifactStore()
    store.update(repo_md_path, frontmatter_updates={"commands": {"test": "python3 -c 'import time; time.sleep(0.1)'"}})

    _write_task(adi_home, repo_id, "TK-001")
    _write_task(adi_home, repo_id, "TK-002", depends_on=["TK-001"])

    assert main(["backlog", "run", "--repo", repo_id, "--max-tasks", "2"]) == 0
    payload = load_yaml(capsys.readouterr().out)

    backlog_run = payload["backlog_run"]
    assert backlog_run["dispatched_tasks"] == 2
    assert backlog_run["completed_tasks"] == 2
    assert backlog_run["failed_tasks"] == 0
    assert [item["task_id"] for item in backlog_run["dispatch_events"]] == ["TK-001", "TK-002"]

    show_1 = main(["task", "show", "TK-001"])
    assert show_1 == 0
    task_1_payload = load_yaml(capsys.readouterr().out)
    assert task_1_payload["task"]["frontmatter"]["status"] == "completed"

    show_2 = main(["task", "show", "TK-002"])
    assert show_2 == 0
    task_2_payload = load_yaml(capsys.readouterr().out)
    assert task_2_payload["task"]["frontmatter"]["status"] == "completed"


def test_backlog_run_tracks_parallel_dispatch_with_worker_pool(tmp_path: Path, monkeypatch) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    loader = ConfigLoader(adi_home=adi_home)
    loader.ensure_initialized()
    loader.save_repos_registry(
        [
            {
                "id": "demo-repo",
                "name": "demo-repo",
                "root": str(tmp_path / "demo-repo"),
                "default_branch": "main",
                "status": "active",
            }
        ]
    )

    (loader.config_dir / "adi.yaml").write_text(
        dump_yaml(
            {
                "execution": {
                    "max_active_runs_global": 2,
                    "max_active_runs_per_repo": 2,
                }
            }
        ),
        encoding="utf-8",
    )

    repo_dir = loader.repos_dir / "demo-repo" / "tasks"
    repo_dir.mkdir(parents=True, exist_ok=True)
    _write_task(adi_home, "demo-repo", "TK-A")
    _write_task(adi_home, "demo-repo", "TK-B")

    fake_task_service = _FakeTaskService()
    backlog_service = BacklogService(
        config_loader=loader,
        task_service=fake_task_service,  # type: ignore[arg-type]
    )

    payload = backlog_service.run(repo_ref="demo-repo", max_tasks=2)
    summary = payload["backlog_run"]

    assert summary["completed_tasks"] == 2
    assert summary["dispatched_tasks"] == 2
    assert summary["max_parallel_seen"] >= 2
    assert set(fake_task_service.calls) == {"TK-A", "TK-B"}
