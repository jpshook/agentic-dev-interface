"""Backlog orchestration services for Phase 5."""

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adi.engine.artifact_store import ArtifactStore
from adi.engine.config_loader import ConfigLoader
from adi.engine.policy_evaluator import PolicyEvaluator
from adi.engine.run_manager import RunManager
from adi.engine.scheduler import Scheduler
from adi.models.task import validate_task_frontmatter
from adi.services.task_service import TaskService


class BacklogService:
    """Backlog visibility and orchestration over repo tasks."""

    def __init__(
        self,
        config_loader: ConfigLoader | None = None,
        artifact_store: ArtifactStore | None = None,
        scheduler: Scheduler | None = None,
        task_service: TaskService | None = None,
        policy_evaluator: PolicyEvaluator | None = None,
    ) -> None:
        self.config_loader = config_loader or ConfigLoader()
        self.artifact_store = artifact_store or ArtifactStore()
        self.scheduler = scheduler or Scheduler()
        self.task_service = task_service or TaskService(config_loader=self.config_loader)
        self.policy_evaluator = policy_evaluator or PolicyEvaluator()

    def show(self, repo_ref: str | None = None) -> dict[str, Any]:
        repo = self._resolve_repo(repo_ref)
        repo_id = str(repo["id"])

        tasks = self._load_repo_tasks(repo_id)
        state_by_id = {str(task["id"]): str(task["status"]) for task in tasks}
        policy_cfg = self._policy_config(repo_id)

        ready: list[str] = []
        blocked: list[str] = []
        running: list[str] = []
        completed: list[str] = []
        failed: list[str] = []
        pending: list[str] = []

        for task in tasks:
            task_id = str(task["id"])
            status = str(task["status"])

            if status == "completed":
                completed.append(task_id)
                continue
            if status == "failed":
                failed.append(task_id)
                continue
            if status in {"in_progress", "pending_verification"}:
                running.append(task_id)
                continue
            if status == "blocked":
                blocked.append(task_id)
                continue
            if status == "proposed":
                pending.append(task_id)
                continue
            if status != "approved":
                pending.append(task_id)
                continue

            dependencies_ok = self._dependencies_satisfied(task, state_by_id)
            if not dependencies_ok:
                blocked.append(task_id)
                continue

            policy_action = self._policy_action(
                task=task,
                dependencies_satisfied=dependencies_ok,
                policy_cfg=policy_cfg,
            )
            if policy_action == "auto_execute":
                ready.append(task_id)
            else:
                pending.append(task_id)

        return {
            "repo": repo,
            "summary": {
                "ready": len(ready),
                "blocked": len(blocked),
                "running": len(running),
                "completed": len(completed),
                "failed": len(failed),
                "pending": len(pending),
                "total": len(tasks),
            },
            "tasks": {
                "ready": sorted(ready),
                "blocked": sorted(blocked),
                "running": sorted(running),
                "completed": sorted(completed),
                "failed": sorted(failed),
                "pending": sorted(pending),
            },
        }

    def run(
        self,
        *,
        repo_ref: str | None = None,
        max_tasks: int | None = None,
        time_limit_seconds: int | None = None,
    ) -> dict[str, Any]:
        repo = self._resolve_repo(repo_ref)
        repo_id = str(repo["id"])

        effective = self.config_loader.load_effective_config(repo_id=repo_id)
        execution_cfg = effective["adi"].get("execution", {})
        max_global = int(execution_cfg.get("max_active_runs_global", 2))
        max_per_repo = int(execution_cfg.get("max_active_runs_per_repo", 2))
        max_parallel = max(1, min(max_global, max_per_repo))

        requested_max_tasks = max_tasks if max_tasks is None else max(0, max_tasks)
        requested_time_limit = (
            time_limit_seconds if time_limit_seconds is None else max(0, time_limit_seconds)
        )

        run_manager = RunManager(self.config_loader.runs_dir)
        backlog_run = run_manager.start_run(repo_id=repo_id, task_id="backlog", mode="backlog")

        started_at = time.monotonic()
        dispatched = 0
        max_parallel_seen = 0
        dispatch_events: list[dict[str, Any]] = []
        completion_events: list[dict[str, Any]] = []
        active: dict[Future[dict[str, Any]], str] = {}

        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            while True:
                finished = [future for future in list(active.keys()) if future.done()]
                for future in finished:
                    task_id = active.pop(future)
                    try:
                        result = future.result()
                        completion_events.append(
                            {
                                "task_id": task_id,
                                "status": str(result.get("status", "failed")),
                                "run_id": result.get("run_id"),
                                "completed_at": self._utc_now(),
                            }
                        )
                    except Exception as exc:
                        completion_events.append(
                            {
                                "task_id": task_id,
                                "status": "failed",
                                "error": str(exc),
                                "completed_at": self._utc_now(),
                            }
                        )

                max_parallel_seen = max(max_parallel_seen, len(active))
                elapsed = int(time.monotonic() - started_at)
                time_exceeded = (
                    requested_time_limit is not None and elapsed >= requested_time_limit
                )
                max_tasks_reached = (
                    requested_max_tasks is not None and dispatched >= requested_max_tasks
                )
                can_dispatch = not time_exceeded and not max_tasks_reached

                if can_dispatch:
                    capacity = max_parallel - len(active)
                    if capacity > 0:
                        eligible = self._eligible_tasks(repo_id, running_task_ids=set(active.values()))
                        if requested_max_tasks is not None:
                            remaining = max(0, requested_max_tasks - dispatched)
                        else:
                            remaining = capacity
                        to_start = self.scheduler.select(eligible, min(capacity, remaining))

                        for task in to_start:
                            task_id = str(task["id"])
                            future = executor.submit(self.task_service.run_task, task_id)
                            active[future] = task_id
                            dispatched += 1
                            dispatch_events.append(
                                {
                                    "task_id": task_id,
                                    "dispatched_at": self._utc_now(),
                                }
                            )
                            max_parallel_seen = max(max_parallel_seen, len(active))

                if active:
                    time.sleep(0.1)
                    continue

                if time_exceeded:
                    stop_reason = "time_limit_reached"
                    break
                if max_tasks_reached:
                    stop_reason = "max_tasks_executed"
                    break

                if not self._eligible_tasks(repo_id, running_task_ids=set()):
                    stop_reason = "no_eligible_tasks"
                    break

                time.sleep(0.05)

        completed_count = sum(1 for item in completion_events if item.get("status") == "completed")
        failed_count = sum(1 for item in completion_events if item.get("status") == "failed")

        summary = {
            "run_id": backlog_run.id,
            "mode": "backlog",
            "repo_id": repo_id,
            "status": "completed" if failed_count == 0 else "completed_with_failures",
            "stop_reason": stop_reason,
            "started_at": backlog_run.created_at,
            "finished_at": self._utc_now(),
            "max_parallel": max_parallel,
            "max_parallel_seen": max_parallel_seen,
            "dispatched_tasks": dispatched,
            "completed_tasks": completed_count,
            "failed_tasks": failed_count,
            "dispatch_events": dispatch_events,
            "completion_events": completion_events,
        }

        run_manager.write_metadata(backlog_run, summary)
        run_manager.write_summary(backlog_run, self._backlog_summary_markdown(summary))

        return {
            "repo": repo,
            "backlog_run": summary,
            "run_dir": str(backlog_run.dir),
        }

    def _eligible_tasks(self, repo_id: str, running_task_ids: set[str]) -> list[dict[str, Any]]:
        tasks = self._load_repo_tasks(repo_id)
        state_by_id = {str(task["id"]): str(task["status"]) for task in tasks}
        policy_cfg = self._policy_config(repo_id)

        policy_actions: dict[str, str] = {}
        for task in tasks:
            task_id = str(task["id"])
            dependencies_ok = self._dependencies_satisfied(task, state_by_id)
            policy_actions[task_id] = self._policy_action(
                task=task,
                dependencies_satisfied=dependencies_ok,
                policy_cfg=policy_cfg,
            )

        return self.scheduler.eligible(
            tasks,
            running_task_ids=running_task_ids,
            policy_actions=policy_actions,
        )

    def _load_repo_tasks(self, repo_id: str) -> list[dict[str, Any]]:
        tasks_dir = self.config_loader.repos_dir / repo_id / "tasks"
        if not tasks_dir.exists():
            return []

        tasks: list[dict[str, Any]] = []
        for path in sorted(tasks_dir.glob("*.md")):
            if not path.is_file():
                continue
            document = self.artifact_store.read(path)
            frontmatter = document.frontmatter
            validate_task_frontmatter(frontmatter)
            tasks.append(dict(frontmatter))
        return tasks

    def _policy_config(self, repo_id: str) -> dict[str, Any]:
        effective = self.config_loader.load_effective_config(repo_id=repo_id)
        policy_cfg = effective.get("policies", {}).get("policy", {})
        return policy_cfg if isinstance(policy_cfg, dict) else {}

    def _policy_action(
        self,
        *,
        task: dict[str, Any],
        dependencies_satisfied: bool,
        policy_cfg: dict[str, Any],
    ) -> str:
        auto_execute_cfg = policy_cfg.get("auto_execute", {})
        restricted_areas = [str(item).lower() for item in policy_cfg.get("restricted_areas", [])]
        touches_restricted = self._touches_restricted_area(task, restricted_areas)

        decision = self.policy_evaluator.evaluate(
            risk=str(task.get("risk", "low")),
            size=str(task.get("size", "small")),
            dependencies_satisfied=dependencies_satisfied,
            touches_restricted_area=touches_restricted,
            auto_max_risk=str(auto_execute_cfg.get("max_risk", "low")),
            auto_max_size=str(auto_execute_cfg.get("max_size", "small")),
        )
        return decision.action

    def _dependencies_satisfied(self, task: dict[str, Any], state_by_id: dict[str, str]) -> bool:
        depends_on = task.get("depends_on", [])
        if not isinstance(depends_on, list):
            return False
        for dep in depends_on:
            if state_by_id.get(str(dep), "") != "completed":
                return False
        return True

    def _touches_restricted_area(self, task: dict[str, Any], restricted: list[str]) -> bool:
        labels: list[str] = []
        for key in ["labels", "tags"]:
            value = task.get(key, [])
            if isinstance(value, list):
                labels.extend(str(item).lower() for item in value)

        title = str(task.get("title", "")).lower()
        for area in restricted:
            if area in title or area in labels:
                return True
        return False

    def _resolve_repo(self, repo_ref: str | None) -> dict[str, Any]:
        repos = self.config_loader.load_repos_registry()
        if repo_ref:
            for repo in repos:
                if repo_ref in {repo.get("id"), repo.get("name")}:
                    return repo
            raise ValueError(f"Unknown repo: {repo_ref}")

        if len(repos) == 1:
            return repos[0]
        if not repos:
            raise ValueError("No repositories registered")
        raise ValueError("Multiple repositories registered; pass --repo")

    def _utc_now(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    def _backlog_summary_markdown(self, summary: dict[str, Any]) -> str:
        lines = [
            "# Backlog Run Summary",
            "",
            f"- Repo: `{summary['repo_id']}`",
            f"- Backlog run id: `{summary['run_id']}`",
            f"- Status: `{summary['status']}`",
            f"- Stop reason: `{summary['stop_reason']}`",
            f"- Dispatched tasks: `{summary['dispatched_tasks']}`",
            f"- Completed tasks: `{summary['completed_tasks']}`",
            f"- Failed tasks: `{summary['failed_tasks']}`",
            f"- Max parallel seen: `{summary['max_parallel_seen']}`",
            "",
            "## Dispatches",
            "",
        ]
        for event in summary.get("dispatch_events", []):
            lines.append(f"- `{event.get('task_id')}` at `{event.get('dispatched_at')}`")
        if not summary.get("dispatch_events"):
            lines.append("- none")
        lines.append("")
        return "\n".join(lines)
