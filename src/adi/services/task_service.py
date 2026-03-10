"""Task execution services for deterministic Phase 3 workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adi.engine.artifact_store import ArtifactDocument, ArtifactStore
from adi.engine.config_loader import ConfigLoader
from adi.engine.lock_manager import LockHandle, LockManager
from adi.engine.policy_evaluator import PolicyEvaluator
from adi.engine.run_manager import RunContext, RunManager
from adi.engine.verifier import Verifier
from adi.engine.worktree_manager import WorktreeManager
from adi.models.task import TaskArtifact, assert_task_transition, validate_task_frontmatter


@dataclass(slots=True)
class TaskRecord:
    """Task with associated repository metadata and on-disk path."""

    repo: dict[str, Any]
    path: Path
    document: ArtifactDocument


class TaskService:
    """Task listing, approval, execution, and verification."""

    def __init__(
        self,
        config_loader: ConfigLoader | None = None,
        artifact_store: ArtifactStore | None = None,
        verifier: Verifier | None = None,
        policy_evaluator: PolicyEvaluator | None = None,
    ) -> None:
        self.config_loader = config_loader or ConfigLoader()
        self.artifact_store = artifact_store or ArtifactStore()
        self.verifier = verifier or Verifier()
        self.policy_evaluator = policy_evaluator or PolicyEvaluator()

    def list_tasks(self, repo_ref: str) -> dict[str, Any]:
        repo = self._resolve_repo(repo_ref)
        tasks = [self._task_summary(path) for path in sorted(self._iter_task_paths(str(repo["id"])))]
        return {"repo": repo, "tasks": tasks}

    def show_task(self, task_id: str) -> dict[str, Any]:
        record = self._resolve_task(task_id)
        return {
            "task": {
                "path": str(record.path),
                "frontmatter": record.document.frontmatter,
                "body": record.document.body,
            },
            "repo": record.repo,
        }

    def approve_task(self, task_id: str) -> dict[str, Any]:
        record = self._resolve_task(task_id)
        frontmatter = record.document.frontmatter
        validate_task_frontmatter(frontmatter)

        current_status = str(frontmatter["status"])
        assert_task_transition(current_status, "approved")

        updated = self._update_task(
            record.path,
            frontmatter_updates={
                "status": "approved",
                "updated_at": self._utc_now(),
            },
        )
        return {
            "task_id": task_id,
            "status": updated.frontmatter["status"],
            "path": str(record.path),
        }

    def run_task(self, task_id: str) -> dict[str, Any]:
        record = self._resolve_task(task_id)
        task = TaskArtifact.from_frontmatter(record.document.frontmatter)

        if task.status != "approved":
            raise ValueError(f"Task must be in 'approved' state to run, got '{task.status}'")

        dependencies_ok = self._dependencies_satisfied(task=task, repo_id=task.repo_id)
        policy_decision = self._evaluate_policy(record=record, dependencies_satisfied=dependencies_ok)
        if policy_decision.action == "deny":
            reason = "; ".join(policy_decision.reasons)
            raise ValueError(f"Task execution denied by policy: {reason}")
        if policy_decision.action == "require_human_input":
            reason = "; ".join(policy_decision.reasons)
            raise ValueError(f"Task execution requires human input: {reason}")

        lock_manager = LockManager(self.config_loader.adi_home / "locks")
        lock_name = f"task-{task.repo_id}-{task.id}"
        lock_handle = lock_manager.acquire(lock_name)

        run_manager = RunManager(self.config_loader.runs_dir)
        run: RunContext | None = None

        try:
            run = run_manager.start_run(repo_id=task.repo_id, task_id=task.id, mode="run")
            self._transition_task(record=record, target="in_progress", run_id=run.id)

            effective = self.config_loader.load_effective_config(repo_id=task.repo_id)
            worktree_root = Path(str(effective["adi"]["execution"]["worktree_root"])).expanduser()
            worktree_manager = WorktreeManager(worktree_root)

            repo_root = Path(str(record.repo["root"])).resolve()
            base_branch = str(record.repo.get("default_branch", "main"))
            worktree_path, branch = worktree_manager.ensure_worktree(
                repo_root=repo_root,
                repo_id=task.repo_id,
                task_id=task.id,
                base_branch=base_branch,
            )

            timeout_seconds = int(effective["adi"]["execution"].get("default_timeout_seconds", 1200))
            repo_commands = self._repo_command_map(task.repo_id)
            check_commands = self.verifier.resolve_commands(task.acceptance_checks, repo_commands)
            verification_results = self.verifier.run_checks(
                repo_root=worktree_path,
                check_commands=check_commands,
                timeout_seconds=timeout_seconds,
            )

            serialized_results = self.verifier.to_serializable(verification_results)
            all_passed = self.verifier.all_passed(verification_results)
            final_status = "completed" if all_passed else "failed"
            self._transition_task(record=record, target=final_status, run_id=run.id)

            metadata = {
                "run_id": run.id,
                "task_id": task.id,
                "repo_id": task.repo_id,
                "mode": "run",
                "status": final_status,
                "created_at": run.created_at,
                "finished_at": self._utc_now(),
                "policy": {
                    "action": policy_decision.action,
                    "reasons": policy_decision.reasons,
                    "metadata": policy_decision.metadata,
                },
                "worktree": {
                    "path": str(worktree_path),
                    "branch": branch,
                },
            }
            run_manager.write_metadata(run, metadata)
            run_manager.write_verification_results(run, serialized_results)
            run_manager.write_command_outputs(run, serialized_results)
            run_manager.write_summary(
                run,
                self._summary_markdown(task=task, final_status=final_status, verification_results=serialized_results),
            )

            return {
                "task_id": task.id,
                "repo_id": task.repo_id,
                "status": final_status,
                "run_id": run.id,
                "run_dir": str(run.dir),
                "worktree": str(worktree_path),
                "policy_action": policy_decision.action,
                "verification": serialized_results,
            }
        except Exception:
            if run is not None:
                self._mark_failed_if_in_progress(task_id=task.id, run_id=run.id)
            raise
        finally:
            lock_manager.release(lock_handle)

    def verify_task(self, task_id: str) -> dict[str, Any]:
        record = self._resolve_task(task_id)
        task = TaskArtifact.from_frontmatter(record.document.frontmatter)

        if task.status not in {"approved", "in_progress", "pending_verification"}:
            raise ValueError(
                "Task must be in approved, in_progress, or pending_verification state to verify"
            )

        dependencies_ok = self._dependencies_satisfied(task=task, repo_id=task.repo_id)
        policy_decision = self._evaluate_policy(record=record, dependencies_satisfied=dependencies_ok)
        if policy_decision.action in {"deny", "require_human_input"}:
            reason = "; ".join(policy_decision.reasons)
            raise ValueError(f"Task verification blocked by policy: {reason}")

        lock_manager = LockManager(self.config_loader.adi_home / "locks")
        lock_name = f"task-{task.repo_id}-{task.id}"
        lock_handle = lock_manager.acquire(lock_name)
        run_manager = RunManager(self.config_loader.runs_dir)

        try:
            run = run_manager.start_run(repo_id=task.repo_id, task_id=task.id, mode="verify")
            current_status = self._reload_frontmatter(record.path).get("status", "")
            if current_status == "approved":
                self._transition_task(record=record, target="in_progress", run_id=run.id)
            current_status = self._reload_frontmatter(record.path).get("status", "")
            if current_status == "in_progress":
                self._transition_task(record=record, target="pending_verification", run_id=run.id)

            effective = self.config_loader.load_effective_config(repo_id=task.repo_id)
            worktree_root = Path(str(effective["adi"]["execution"]["worktree_root"])).expanduser()
            worktree_manager = WorktreeManager(worktree_root)
            repo_root = Path(str(record.repo["root"])).resolve()
            base_branch = str(record.repo.get("default_branch", "main"))
            worktree_path, branch = worktree_manager.ensure_worktree(
                repo_root=repo_root,
                repo_id=task.repo_id,
                task_id=task.id,
                base_branch=base_branch,
            )

            timeout_seconds = int(effective["adi"]["execution"].get("default_timeout_seconds", 1200))
            repo_commands = self._repo_command_map(task.repo_id)
            check_commands = self.verifier.resolve_commands(task.acceptance_checks, repo_commands)
            verification_results = self.verifier.run_checks(
                repo_root=worktree_path,
                check_commands=check_commands,
                timeout_seconds=timeout_seconds,
            )
            serialized_results = self.verifier.to_serializable(verification_results)
            final_status = "completed" if self.verifier.all_passed(verification_results) else "failed"
            self._transition_task(record=record, target=final_status, run_id=run.id)

            metadata = {
                "run_id": run.id,
                "task_id": task.id,
                "repo_id": task.repo_id,
                "mode": "verify",
                "status": final_status,
                "created_at": run.created_at,
                "finished_at": self._utc_now(),
                "policy": {
                    "action": policy_decision.action,
                    "reasons": policy_decision.reasons,
                    "metadata": policy_decision.metadata,
                },
                "worktree": {
                    "path": str(worktree_path),
                    "branch": branch,
                },
            }
            run_manager.write_metadata(run, metadata)
            run_manager.write_verification_results(run, serialized_results)
            run_manager.write_command_outputs(run, serialized_results)
            run_manager.write_summary(
                run,
                self._summary_markdown(task=task, final_status=final_status, verification_results=serialized_results),
            )

            return {
                "task_id": task.id,
                "repo_id": task.repo_id,
                "status": final_status,
                "run_id": run.id,
                "run_dir": str(run.dir),
                "worktree": str(worktree_path),
                "policy_action": policy_decision.action,
                "verification": serialized_results,
            }
        finally:
            lock_manager.release(lock_handle)

    def _task_summary(self, path: Path) -> dict[str, Any]:
        document = self.artifact_store.read(path)
        frontmatter = document.frontmatter
        validate_task_frontmatter(frontmatter)
        return {
            "id": frontmatter["id"],
            "title": frontmatter["title"],
            "status": frontmatter["status"],
            "priority": frontmatter["priority"],
            "size": frontmatter["size"],
            "risk": frontmatter["risk"],
            "path": str(path),
        }

    def _resolve_task(self, task_id: str) -> TaskRecord:
        repos = self.config_loader.load_repos_registry()
        matches: list[TaskRecord] = []
        for repo in repos:
            repo_id = str(repo.get("id", ""))
            for path in self._iter_task_paths(repo_id):
                document = self.artifact_store.read(path)
                frontmatter = document.frontmatter
                if str(frontmatter.get("id", "")) != task_id:
                    continue
                if str(frontmatter.get("repo_id", "")) != repo_id:
                    raise ValueError(f"Task '{task_id}' repo_id does not match registry repo '{repo_id}'")
                validate_task_frontmatter(frontmatter)
                matches.append(TaskRecord(repo=repo, path=path, document=document))

        if not matches:
            raise ValueError(f"Unknown task: {task_id}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous task id '{task_id}' across repositories")
        return matches[0]

    def _resolve_repo(self, repo_ref: str) -> dict[str, Any]:
        repos = self.config_loader.load_repos_registry()
        for repo in repos:
            if repo_ref in {repo.get("id"), repo.get("name")}:
                return repo
        raise ValueError(f"Unknown repo: {repo_ref}")

    def _iter_task_paths(self, repo_id: str) -> list[Path]:
        tasks_dir = self.config_loader.repos_dir / repo_id / "tasks"
        if not tasks_dir.exists():
            return []
        return [path for path in tasks_dir.glob("*.md") if path.is_file()]

    def _dependencies_satisfied(self, task: TaskArtifact, repo_id: str) -> bool:
        if not task.depends_on:
            return True

        task_states: dict[str, str] = {}
        for path in self._iter_task_paths(repo_id):
            document = self.artifact_store.read(path)
            frontmatter = document.frontmatter
            task_states[str(frontmatter.get("id", ""))] = str(frontmatter.get("status", ""))

        for dependency in task.depends_on:
            if task_states.get(dependency) != "completed":
                return False
        return True

    def _evaluate_policy(self, record: TaskRecord, dependencies_satisfied: bool):
        frontmatter = record.document.frontmatter
        effective = self.config_loader.load_effective_config(repo_id=str(record.repo["id"]))
        policy_cfg = effective["policies"].get("policy", {})
        auto_execute_cfg = policy_cfg.get("auto_execute", {})
        restricted_areas = policy_cfg.get("restricted_areas", [])

        touches_restricted = self._touches_restricted_area(frontmatter, restricted_areas)
        return self.policy_evaluator.evaluate(
            risk=str(frontmatter["risk"]),
            size=str(frontmatter["size"]),
            dependencies_satisfied=dependencies_satisfied,
            touches_restricted_area=touches_restricted,
            auto_max_risk=str(auto_execute_cfg.get("max_risk", "low")),
            auto_max_size=str(auto_execute_cfg.get("max_size", "small")),
        )

    def _touches_restricted_area(self, frontmatter: dict[str, Any], restricted: list[str]) -> bool:
        label_candidates: list[str] = []
        for key in ["labels", "tags"]:
            value = frontmatter.get(key, [])
            if isinstance(value, list):
                label_candidates.extend(str(item).lower() for item in value)

        title = str(frontmatter.get("title", "")).lower()
        for area in restricted:
            marker = str(area).lower()
            if marker in title:
                return True
            if marker in label_candidates:
                return True
        return False

    def _repo_command_map(self, repo_id: str) -> dict[str, str]:
        repo_md_path = self.config_loader.repos_dir / repo_id / "repo.md"
        if not repo_md_path.exists():
            return {}
        document = self.artifact_store.read(repo_md_path)
        commands = document.frontmatter.get("commands", {})
        return commands if isinstance(commands, dict) else {}

    def _update_task(self, task_path: Path, frontmatter_updates: dict[str, Any]) -> ArtifactDocument:
        return self.artifact_store.update(
            task_path,
            frontmatter_updates=frontmatter_updates,
            validator=validate_task_frontmatter,
        )

    def _transition_task(self, record: TaskRecord, target: str, run_id: str) -> None:
        current = str(self._reload_frontmatter(record.path).get("status", ""))
        assert_task_transition(current, target)
        self._update_task(
            record.path,
            frontmatter_updates={
                "status": target,
                "updated_at": self._utc_now(),
                "last_run_id": run_id,
            },
        )

    def _mark_failed_if_in_progress(self, task_id: str, run_id: str) -> None:
        record = self._resolve_task(task_id)
        current = str(record.document.frontmatter.get("status", ""))
        if current == "in_progress":
            self._update_task(
                record.path,
                frontmatter_updates={
                    "status": "failed",
                    "updated_at": self._utc_now(),
                    "last_run_id": run_id,
                },
            )

    def _reload_frontmatter(self, path: Path) -> dict[str, Any]:
        return self.artifact_store.read(path).frontmatter

    def _utc_now(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    def _summary_markdown(
        self,
        *,
        task: TaskArtifact,
        final_status: str,
        verification_results: list[dict[str, object]],
    ) -> str:
        lines = [
            f"# Run Summary {task.id}",
            "",
            f"- Repo: `{task.repo_id}`",
            f"- Task: `{task.id}`",
            f"- Final status: `{final_status}`",
            "",
            "## Verification",
            "",
        ]
        for item in verification_results:
            check = item.get("check", "")
            returncode = item.get("returncode", "")
            command = item.get("command", "")
            lines.append(f"- `{check}` -> `{returncode}` via `{command}`")
        if not verification_results:
            lines.append("- No verification results")
        lines.append("")
        return "\n".join(lines)
