from pathlib import Path

from adi.engine.config_loader import ConfigLoader
from adi.engine.yaml_utils import dump_yaml
from adi.services.orchestrator_service import MultiRepoOrchestrator


def test_orchestrator_runs_cross_repo_tasks_with_dependency_order(tmp_path: Path) -> None:
    adi_home = tmp_path / ".adi-home"
    loader = ConfigLoader(adi_home=adi_home)
    loader.ensure_initialized()
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

    repo_a_root = tmp_path / "repo-a"
    repo_b_root = tmp_path / "repo-b"
    repo_a_root.mkdir(parents=True, exist_ok=True)
    repo_b_root.mkdir(parents=True, exist_ok=True)

    loader.save_repos_registry(
        [
            {
                "id": "repo-a",
                "name": "repo-a",
                "root": str(repo_a_root),
                "default_branch": "main",
                "status": "active",
            },
            {
                "id": "repo-b",
                "name": "repo-b",
                "root": str(repo_b_root),
                "default_branch": "main",
                "status": "active",
            },
        ]
    )

    call_order: list[str] = []

    def runner(task_id: str) -> dict[str, object]:
        call_order.append(task_id)
        return {
            "task_id": task_id,
            "status": "completed",
            "run_id": f"run-{task_id}",
        }

    orchestrator = MultiRepoOrchestrator(config_loader=loader)
    result = orchestrator.run(
        spec_id="SP-100",
        tasks=[
            {"id": "TK-A-001", "repo_id": "repo-a", "status": "approved", "depends_on": []},
            {"id": "TK-B-001", "repo_id": "repo-b", "status": "approved", "depends_on": ["TK-A-001"]},
        ],
        task_runner=runner,
    )

    assert result["status"] == "completed"
    assert result["stop_reason"] == "all_tasks_resolved"
    assert result["dispatched_tasks"] == 2
    assert result["completed_tasks"] == 2
    assert [item["task_id"] for item in result["dispatch_events"]] == ["TK-A-001", "TK-B-001"]
    assert call_order == ["TK-A-001", "TK-B-001"]


def test_orchestrator_blocks_on_invalid_dependency_graph(tmp_path: Path) -> None:
    loader = ConfigLoader(adi_home=tmp_path / ".adi-home")
    loader.ensure_initialized()

    orchestrator = MultiRepoOrchestrator(config_loader=loader)
    result = orchestrator.run(
        spec_id="SP-CYCLE",
        tasks=[
            {"id": "TK-1", "repo_id": "repo-a", "status": "approved", "depends_on": ["TK-2"]},
            {"id": "TK-2", "repo_id": "repo-b", "status": "approved", "depends_on": ["TK-1"]},
        ],
        task_runner=lambda _task_id: {"status": "completed"},
    )

    assert result["status"] == "blocked"
    assert result["stop_reason"] == "dependency_graph_inconsistent"
    assert "Dependency graph contains a cycle" in result["errors"]
