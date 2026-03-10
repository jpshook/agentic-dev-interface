"""Cross-repository task orchestration for multi-repo spec execution."""

from __future__ import annotations

import time
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from adi.engine.config_loader import ConfigLoader
from adi.engine.run_manager import RunManager
from adi.engine.yaml_utils import dump_yaml

TaskRunner = Callable[[str], dict[str, Any]]


@dataclass(slots=True)
class OrchestrationTask:
    id: str
    repo_id: str
    status: str
    depends_on: list[str]


class MultiRepoOrchestrator:
    """Coordinate task execution across repositories with cross-repo dependencies."""

    def __init__(self, config_loader: ConfigLoader | None = None) -> None:
        self.config_loader = config_loader or ConfigLoader()

    def run(
        self,
        *,
        spec_id: str,
        tasks: list[dict[str, Any]],
        task_runner: TaskRunner,
        max_tasks: int | None = None,
        time_limit_seconds: int | None = None,
    ) -> dict[str, Any]:
        parsed = [self._parse_task(item) for item in tasks]
        graph_check = self._validate_graph(parsed)
        if not graph_check["ok"]:
            return {
                "mode": "spec-orchestrate",
                "spec_id": spec_id,
                "status": "blocked",
                "stop_reason": "dependency_graph_inconsistent",
                "errors": graph_check["errors"],
                "dispatch_events": [],
                "completion_events": [],
                "completed_tasks": 0,
                "failed_tasks": 0,
                "max_parallel_seen": 0,
            }

        repo_check = self._validate_repo_availability(parsed)
        if not repo_check["ok"]:
            return {
                "mode": "spec-orchestrate",
                "spec_id": spec_id,
                "status": "blocked",
                "stop_reason": "required_repo_unavailable",
                "errors": repo_check["errors"],
                "dispatch_events": [],
                "completion_events": [],
                "completed_tasks": 0,
                "failed_tasks": 0,
                "max_parallel_seen": 0,
            }

        execution_cfg = self.config_loader.load_effective_config().get("adi", {}).get("execution", {})
        max_global = int(execution_cfg.get("max_active_runs_global", 2))
        max_per_repo = int(execution_cfg.get("max_active_runs_per_repo", 2))
        max_workers = max(1, max_global)

        requested_max_tasks = max_tasks if max_tasks is None else max(0, int(max_tasks))
        requested_time_limit = (
            time_limit_seconds if time_limit_seconds is None else max(0, int(time_limit_seconds))
        )

        run_manager = RunManager(self.config_loader.runs_dir)
        run = run_manager.start_run(repo_id="multi-repo", task_id=spec_id, mode="spec-orchestrate")

        by_id = {task.id: task for task in parsed}
        completed: set[str] = {
            task.id for task in parsed if task.status == "completed"
        }
        failed: set[str] = {
            task.id for task in parsed if task.status in {"failed", "blocked"}
        }
        pending: set[str] = {
            task.id for task in parsed if task.status == "approved"
        }

        active: dict[Future[dict[str, Any]], str] = {}
        running_per_repo: dict[str, int] = defaultdict(int)
        dispatched_count = 0
        dispatch_events: list[dict[str, Any]] = []
        completion_events: list[dict[str, Any]] = []
        max_parallel_seen = 0
        started = time.monotonic()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            while True:
                finished = [future for future in list(active.keys()) if future.done()]
                for future in finished:
                    task_id = active.pop(future)
                    task = by_id[task_id]
                    running_per_repo[task.repo_id] = max(0, running_per_repo[task.repo_id] - 1)
                    try:
                        result = future.result()
                        status = str(result.get("status", "failed"))
                        completion_events.append(
                            {
                                "task_id": task_id,
                                "repo_id": task.repo_id,
                                "status": status,
                                "run_id": result.get("run_id"),
                                "completed_at": self._utc_now(),
                            }
                        )
                        if status == "completed":
                            completed.add(task_id)
                        else:
                            failed.add(task_id)
                    except Exception as exc:
                        failed.add(task_id)
                        completion_events.append(
                            {
                                "task_id": task_id,
                                "repo_id": task.repo_id,
                                "status": "failed",
                                "error": str(exc),
                                "completed_at": self._utc_now(),
                            }
                        )

                pending = {task_id for task_id in pending if task_id not in completed and task_id not in failed}
                max_parallel_seen = max(max_parallel_seen, len(active))

                elapsed = int(time.monotonic() - started)
                if requested_time_limit is not None and elapsed >= requested_time_limit:
                    stop_reason = "time_limit_reached"
                    break
                if requested_max_tasks is not None and dispatched_count >= requested_max_tasks:
                    stop_reason = "max_tasks_executed"
                    break

                runnable = [
                    by_id[task_id]
                    for task_id in sorted(pending)
                    if self._deps_satisfied(by_id[task_id], completed)
                    and running_per_repo[by_id[task_id].repo_id] < max_per_repo
                ]

                capacity = max_workers - len(active)
                if requested_max_tasks is not None:
                    remaining = max(0, requested_max_tasks - dispatched_count)
                    capacity = min(capacity, remaining)

                if capacity > 0 and runnable:
                    for task in runnable[:capacity]:
                        future = executor.submit(task_runner, task.id)
                        active[future] = task.id
                        running_per_repo[task.repo_id] += 1
                        dispatched_count += 1
                        dispatch_events.append(
                            {
                                "task_id": task.id,
                                "repo_id": task.repo_id,
                                "dispatched_at": self._utc_now(),
                            }
                        )
                        max_parallel_seen = max(max_parallel_seen, len(active))

                if active:
                    time.sleep(0.1)
                    continue

                if not pending:
                    stop_reason = "all_tasks_resolved"
                    break

                runnable_without_limit = [
                    by_id[task_id]
                    for task_id in sorted(pending)
                    if self._deps_satisfied(by_id[task_id], completed)
                ]
                if not runnable_without_limit:
                    stop_reason = "cross_repo_dependencies_blocked"
                    break

                time.sleep(0.05)

        status = "completed"
        if failed:
            status = "completed_with_failures"
        if stop_reason in {"cross_repo_dependencies_blocked", "required_repo_unavailable", "dependency_graph_inconsistent"}:
            status = "blocked"

        summary = {
            "run_id": run.id,
            "mode": "spec-orchestrate",
            "spec_id": spec_id,
            "status": status,
            "stop_reason": stop_reason,
            "started_at": run.created_at,
            "finished_at": self._utc_now(),
            "total_tasks": len(parsed),
            "approved_tasks": len([task for task in parsed if task.status == "approved"]),
            "dispatched_tasks": dispatched_count,
            "completed_tasks": len(completed),
            "failed_tasks": len(failed),
            "max_parallel": max_workers,
            "max_parallel_seen": max_parallel_seen,
            "dispatch_events": dispatch_events,
            "completion_events": completion_events,
            "dependency_graph": {
                task.id: list(task.depends_on)
                for task in sorted(parsed, key=lambda item: item.id)
            },
        }

        run_manager.write_metadata(run, summary)
        run_manager.write_summary(run, self._summary_markdown(summary))
        graph_path = run.dir / "dependency_graph.yaml"
        graph_path.write_text(dump_yaml(summary["dependency_graph"]), encoding="utf-8")

        return summary | {"run_dir": str(run.dir)}

    def _parse_task(self, payload: dict[str, Any]) -> OrchestrationTask:
        task_id = str(payload.get("id", "")).strip()
        repo_id = str(payload.get("repo_id", "")).strip()
        status = str(payload.get("status", "")).strip()
        depends_on_raw = payload.get("depends_on", [])
        depends_on = [str(item) for item in depends_on_raw] if isinstance(depends_on_raw, list) else []
        return OrchestrationTask(
            id=task_id,
            repo_id=repo_id,
            status=status,
            depends_on=depends_on,
        )

    def _validate_graph(self, tasks: list[OrchestrationTask]) -> dict[str, Any]:
        by_id = {task.id: task for task in tasks}
        errors: list[str] = []

        for task in tasks:
            if not task.id:
                errors.append("Task with empty id found")
                continue
            if not task.repo_id:
                errors.append(f"Task {task.id} missing repo_id")
            for dep in task.depends_on:
                if dep not in by_id:
                    errors.append(f"Task {task.id} depends on unknown task {dep}")

        if errors:
            return {"ok": False, "errors": sorted(set(errors))}

        visited: set[str] = set()
        visiting: set[str] = set()

        def dfs(task_id: str) -> bool:
            if task_id in visited:
                return False
            if task_id in visiting:
                return True
            visiting.add(task_id)
            for dep in by_id[task_id].depends_on:
                if dfs(dep):
                    return True
            visiting.remove(task_id)
            visited.add(task_id)
            return False

        has_cycle = any(dfs(task.id) for task in tasks)
        if has_cycle:
            return {"ok": False, "errors": ["Dependency graph contains a cycle"]}
        return {"ok": True, "errors": []}

    def _validate_repo_availability(self, tasks: list[OrchestrationTask]) -> dict[str, Any]:
        repos = {str(repo.get("id", "")): repo for repo in self.config_loader.load_repos_registry()}
        errors: list[str] = []

        for repo_id in sorted({task.repo_id for task in tasks}):
            entry = repos.get(repo_id)
            if entry is None:
                errors.append(f"Required repo not registered: {repo_id}")
                continue
            root = Path(str(entry.get("root", ""))).expanduser().resolve()
            if not root.exists() or not root.is_dir():
                errors.append(f"Required repo unavailable: {repo_id} ({root})")

        return {"ok": not errors, "errors": errors}

    def _deps_satisfied(self, task: OrchestrationTask, completed: set[str]) -> bool:
        return all(dep in completed for dep in task.depends_on)

    def _summary_markdown(self, summary: dict[str, Any]) -> str:
        lines = [
            "# Multi-Repo Orchestration Summary",
            "",
            f"- Spec: `{summary['spec_id']}`",
            f"- Status: `{summary['status']}`",
            f"- Stop reason: `{summary['stop_reason']}`",
            f"- Approved tasks: `{summary['approved_tasks']}`",
            f"- Dispatched tasks: `{summary['dispatched_tasks']}`",
            f"- Completed tasks: `{summary['completed_tasks']}`",
            f"- Failed tasks: `{summary['failed_tasks']}`",
            f"- Max parallel seen: `{summary['max_parallel_seen']}`",
            "",
            "## Timeline",
            "",
        ]
        for item in summary.get("dispatch_events", []):
            lines.append(
                f"- Dispatch `{item.get('task_id')}` ({item.get('repo_id')}) at `{item.get('dispatched_at')}`"
            )
        if not summary.get("dispatch_events"):
            lines.append("- none")
        lines.append("")
        return "\n".join(lines)

    def _utc_now(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()
