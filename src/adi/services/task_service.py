"""Task execution services for deterministic + agent-assisted workflows."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adi.engine.agent_runner import AgentRunner
from adi.engine.artifact_store import ArtifactDocument, ArtifactStore
from adi.engine.config_loader import ConfigLoader
from adi.engine.lock_manager import LockManager
from adi.engine.policy_evaluator import PolicyEvaluator
from adi.engine.prompt_builder import PromptBuilder
from adi.engine.run_manager import RunContext, RunManager
from adi.engine.verifier import Verifier
from adi.engine.worktree_manager import WorktreeManager
from adi.engine.yaml_utils import load_yaml
from adi.models.policy import PolicyDecision
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
        prompt_builder: PromptBuilder | None = None,
        agent_runner: AgentRunner | None = None,
    ) -> None:
        self.config_loader = config_loader or ConfigLoader()
        self.artifact_store = artifact_store or ArtifactStore()
        self.verifier = verifier or Verifier()
        self.policy_evaluator = policy_evaluator or PolicyEvaluator()
        self.prompt_builder = prompt_builder or PromptBuilder(config_loader=self.config_loader)
        self.agent_runner = agent_runner or AgentRunner(config_loader=self.config_loader)

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

    def delete_task(self, task_id: str) -> dict[str, Any]:
        record = self._resolve_task(task_id)
        task = TaskArtifact.from_frontmatter(record.document.frontmatter)

        run_dirs = self._delete_task_runs(task_id=task.id, repo_id=task.repo_id)
        worktree_deleted = self._delete_task_worktree(task=task, repo_root=Path(str(record.repo["root"])).resolve())

        if record.path.exists():
            record.path.unlink()

        return {
            "task_id": task.id,
            "repo_id": task.repo_id,
            "deleted": True,
            "path": str(record.path),
            "deleted_run_dirs": run_dirs,
            "deleted_worktree": worktree_deleted,
        }

    def run_task(self, task_id: str) -> dict[str, Any]:
        record = self._resolve_task(task_id)
        task = TaskArtifact.from_frontmatter(record.document.frontmatter)

        if task.status != "approved":
            raise ValueError(f"Task must be in 'approved' state to run, got '{task.status}'")

        dependencies_ok = self._dependencies_satisfied(task=task, repo_id=task.repo_id)
        policy_decision, restricted_areas = self._evaluate_policy(
            record=record,
            dependencies_satisfied=dependencies_ok,
        )
        if policy_decision.action != "auto_execute":
            reason = "; ".join(policy_decision.reasons)
            raise ValueError(f"Task execution blocked by policy ({policy_decision.action}): {reason}")

        effective = self.config_loader.load_effective_config(repo_id=task.repo_id)
        execution_cfg = effective["adi"].get("execution", {})
        timeout_seconds = int(execution_cfg.get("default_timeout_seconds", 1200))
        max_attempts = self._max_attempts(execution_cfg)

        lock_manager = LockManager(self.config_loader.adi_home / "locks")
        lock_name = f"task-{task.repo_id}-{task.id}"
        lock_handle = lock_manager.acquire(lock_name)

        run_manager = RunManager(self.config_loader.runs_dir)
        run: RunContext | None = None

        try:
            run = run_manager.start_run(repo_id=task.repo_id, task_id=task.id, mode="run")
            self._transition_task(record=record, target="in_progress", run_id=run.id)

            worktree_path, branch = self._prepare_worktree(task=task, record=record, effective=effective)
            repo_root = Path(str(record.repo["root"])).resolve()
            base_repo_status = self._git_status_snapshot(repo_root)
            repo_frontmatter = self._repo_frontmatter(task.repo_id)
            check_commands = self.verifier.resolve_commands(
                acceptance_checks=task.acceptance_checks,
                repo_command_map=self._repo_command_map(task.repo_id),
            )

            attempt_history: list[dict[str, Any]] = []
            verification_results: list[dict[str, object]] = []
            final_status = "failed"
            failure_reason = "Verification did not pass"

            for attempt in range(1, max_attempts + 1):
                retry_context = self._retry_context(attempt_history)
                prompt = self.prompt_builder.build(
                    role="implementer",
                    repo_id=task.repo_id,
                    run_id=run.id,
                    attempt=attempt,
                    worktree_path=worktree_path,
                    task_frontmatter=self._reload_frontmatter(record.path),
                    task_body=self.artifact_store.read(record.path).body,
                    repo_frontmatter=repo_frontmatter,
                    spec_context=self._spec_context(self._reload_frontmatter(record.path)),
                    retry_context=retry_context,
                )
                prompt_path = run_manager.write_prompt(run, role="implementer", attempt=attempt, prompt=prompt)

                agent_result = self.agent_runner.run(
                    role="implementer",
                    repo_id=task.repo_id,
                    prompt=prompt,
                    prompt_path=prompt_path,
                    worktree_path=worktree_path,
                    run_dir=run.dir,
                    attempt=attempt,
                )
                run_manager.write_agent_result(
                    run,
                    role="implementer",
                    attempt=attempt,
                    payload=agent_result.to_dict(),
                )

                self._assert_primary_workspace_unchanged(repo_root, base_repo_status)
                restricted_paths = self._modified_restricted_paths(worktree_path, restricted_areas)
                if restricted_paths:
                    failure_reason = "Agent modified restricted paths"
                    attempt_history.append(
                        {
                            "attempt": attempt,
                            "agent_success": agent_result.success,
                            "verification_passed": False,
                            "reason": f"restricted paths: {', '.join(sorted(restricted_paths))}",
                        }
                    )
                    break

                verification = self.verifier.run_checks(
                    repo_root=worktree_path,
                    check_commands=check_commands,
                    timeout_seconds=timeout_seconds,
                )
                verification_results = self.verifier.to_serializable(verification)
                verification_passed = self.verifier.all_passed(verification)
                run_manager.write_verification_results(run, verification_results, attempt=attempt)
                run_manager.write_command_outputs(run, verification_results, attempt=attempt)

                attempt_history.append(
                    {
                        "attempt": attempt,
                        "agent_success": agent_result.success,
                        "verification_passed": verification_passed,
                        "reason": "ok" if verification_passed else "verification failed",
                    }
                )

                if agent_result.success and verification_passed:
                    final_status = "completed"
                    failure_reason = ""
                    break

                failure_reason = (
                    "agent execution failed" if not agent_result.success else "verification checks failed"
                )

            if final_status == "completed":
                self._transition_task(record=record, target="completed", run_id=run.id)
            else:
                self._transition_task(record=record, target="failed", run_id=run.id)

            run_manager.write_metadata(
                run,
                {
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
                    "attempts": attempt_history,
                    "failure_reason": failure_reason,
                },
            )
            run_manager.write_verification_results(run, verification_results)
            run_manager.write_command_outputs(run, verification_results)
            run_manager.write_diff_summary(run, self._git_diff(worktree_path))
            run_manager.write_summary(
                run,
                self._summary_markdown(
                    task=task,
                    final_status=final_status,
                    verification_results=verification_results,
                    attempt_history=attempt_history,
                ),
            )

            return {
                "task_id": task.id,
                "repo_id": task.repo_id,
                "status": final_status,
                "run_id": run.id,
                "run_dir": str(run.dir),
                "worktree": str(worktree_path),
                "policy_action": policy_decision.action,
                "attempts": attempt_history,
                "verification": verification_results,
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
            timeout_seconds = int(effective["adi"]["execution"].get("default_timeout_seconds", 1200))
            worktree_path, branch = self._prepare_worktree(task=task, record=record, effective=effective)

            check_commands = self.verifier.resolve_commands(
                acceptance_checks=task.acceptance_checks,
                repo_command_map=self._repo_command_map(task.repo_id),
            )
            verification_objects = self.verifier.run_checks(
                repo_root=worktree_path,
                check_commands=check_commands,
                timeout_seconds=timeout_seconds,
            )
            verification_results = self.verifier.to_serializable(verification_objects)
            final_status = "completed" if self.verifier.all_passed(verification_objects) else "failed"

            self._transition_task(record=record, target=final_status, run_id=run.id)

            run_manager.write_metadata(
                run,
                {
                    "run_id": run.id,
                    "task_id": task.id,
                    "repo_id": task.repo_id,
                    "mode": "verify",
                    "status": final_status,
                    "created_at": run.created_at,
                    "finished_at": self._utc_now(),
                    "worktree": {
                        "path": str(worktree_path),
                        "branch": branch,
                    },
                },
            )
            run_manager.write_verification_results(run, verification_results)
            run_manager.write_command_outputs(run, verification_results)
            run_manager.write_summary(
                run,
                self._summary_markdown(
                    task=task,
                    final_status=final_status,
                    verification_results=verification_results,
                    attempt_history=[],
                ),
            )

            return {
                "task_id": task.id,
                "repo_id": task.repo_id,
                "status": final_status,
                "run_id": run.id,
                "run_dir": str(run.dir),
                "worktree": str(worktree_path),
                "verification": verification_results,
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

    def _evaluate_policy(
        self,
        *,
        record: TaskRecord,
        dependencies_satisfied: bool,
    ) -> tuple[PolicyDecision, list[str]]:
        frontmatter = record.document.frontmatter
        effective = self.config_loader.load_effective_config(repo_id=str(record.repo["id"]))
        policy_cfg = effective["policies"].get("policy", {})
        auto_execute_cfg = policy_cfg.get("auto_execute", {})
        restricted_areas = [str(item).lower() for item in policy_cfg.get("restricted_areas", [])]

        touches_restricted = self._touches_restricted_area(frontmatter, restricted_areas)
        decision = self.policy_evaluator.evaluate(
            risk=str(frontmatter["risk"]),
            size=str(frontmatter["size"]),
            dependencies_satisfied=dependencies_satisfied,
            touches_restricted_area=touches_restricted,
            auto_max_risk=str(auto_execute_cfg.get("max_risk", "low")),
            auto_max_size=str(auto_execute_cfg.get("max_size", "small")),
        )
        return decision, restricted_areas

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

    def _repo_frontmatter(self, repo_id: str) -> dict[str, Any]:
        repo_md_path = self.config_loader.repos_dir / repo_id / "repo.md"
        if not repo_md_path.exists():
            return {}
        return self.artifact_store.read(repo_md_path).frontmatter

    def _spec_context(self, task_frontmatter: dict[str, Any]) -> str:
        spec_id = str(task_frontmatter.get("spec_id", "")).strip()
        repo_id = str(task_frontmatter.get("repo_id", "")).strip()
        if not spec_id or not repo_id:
            return ""

        specs_dir = self.config_loader.repos_dir / repo_id / "specs"
        direct_path = specs_dir / f"{spec_id}.md"
        if direct_path.exists():
            return self.artifact_store.read(direct_path).body

        for path in specs_dir.glob("*.md"):
            document = self.artifact_store.read(path)
            if str(document.frontmatter.get("id", "")) == spec_id:
                return document.body
        return ""

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

    def _delete_task_runs(self, *, task_id: str, repo_id: str) -> list[str]:
        deleted: list[str] = []
        for run_dir in self._matching_run_dirs(task_id=task_id, repo_id=repo_id):
            shutil.rmtree(run_dir, ignore_errors=True)
            deleted.append(str(run_dir))
        return deleted

    def _matching_run_dirs(self, *, task_id: str, repo_id: str) -> list[Path]:
        matches: list[Path] = []
        if not self.config_loader.runs_dir.exists():
            return matches

        for run_dir in self.config_loader.runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            metadata_path = run_dir / "metadata.yaml"
            if not metadata_path.exists():
                continue
            payload = load_yaml(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            if str(payload.get("task_id", "")) != task_id:
                continue
            if str(payload.get("repo_id", "")) != repo_id:
                continue
            matches.append(run_dir)
        return matches

    def _delete_task_worktree(self, *, task: TaskArtifact, repo_root: Path) -> bool:
        effective = self.config_loader.load_effective_config(repo_id=task.repo_id)
        worktree_root = Path(str(effective["adi"]["execution"]["worktree_root"])).expanduser()
        manager = WorktreeManager(worktree_root)
        worktree_path = manager.path_for_task(task.repo_id, task.id)
        branch = manager.branch_for_task(task.id)

        if worktree_path.exists():
            result = subprocess.run(
                ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 and worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)

        subprocess.run(
            ["git", "-C", str(repo_root), "branch", "-D", branch],
            check=False,
            capture_output=True,
            text=True,
        )

        self._remove_empty_parents(worktree_path, stop_at=worktree_root)
        return not worktree_path.exists()

    def _remove_empty_parents(self, path: Path, *, stop_at: Path) -> None:
        current = path.parent
        stop = stop_at.resolve()
        while current.exists() and current != stop:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _utc_now(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    def _summary_markdown(
        self,
        *,
        task: TaskArtifact,
        final_status: str,
        verification_results: list[dict[str, object]],
        attempt_history: list[dict[str, Any]],
    ) -> str:
        lines = [
            f"# Run Summary {task.id}",
            "",
            f"- Repo: `{task.repo_id}`",
            f"- Task: `{task.id}`",
            f"- Final status: `{final_status}`",
            "",
            "## Attempts",
            "",
        ]
        if attempt_history:
            for item in attempt_history:
                lines.append(
                    f"- Attempt `{item.get('attempt')}`: agent_success=`{item.get('agent_success')}` verification_passed=`{item.get('verification_passed')}` reason=`{item.get('reason')}`"
                )
        else:
            lines.append("- No attempt history")

        lines.extend([
            "",
            "## Verification",
            "",
        ])
        for item in verification_results:
            check = item.get("check", "")
            returncode = item.get("returncode", "")
            command = item.get("command", "")
            lines.append(f"- `{check}` -> `{returncode}` via `{command}`")
        if not verification_results:
            lines.append("- No verification results")
        lines.append("")
        return "\n".join(lines)

    def _prepare_worktree(
        self,
        *,
        task: TaskArtifact,
        record: TaskRecord,
        effective: dict[str, Any],
    ) -> tuple[Path, str]:
        worktree_root = Path(str(effective["adi"]["execution"]["worktree_root"])).expanduser()
        worktree_manager = WorktreeManager(worktree_root)

        repo_root = Path(str(record.repo["root"])).resolve()
        base_branch = str(record.repo.get("default_branch", "main"))
        return worktree_manager.ensure_worktree(
            repo_root=repo_root,
            repo_id=task.repo_id,
            task_id=task.id,
            base_branch=base_branch,
        )

    def _retry_context(self, attempts: list[dict[str, Any]]) -> str:
        if not attempts:
            return ""
        lines = ["Previous attempts:"]
        for item in attempts:
            lines.append(
                f"- attempt {item.get('attempt')}: agent_success={item.get('agent_success')} verification_passed={item.get('verification_passed')} reason={item.get('reason')}"
            )
        return "\n".join(lines)

    def _max_attempts(self, execution_cfg: dict[str, Any]) -> int:
        verification_fix_cycles = int(execution_cfg.get("verification_fix_cycles", 2))
        total_task_attempts = int(execution_cfg.get("total_task_attempts", 3))
        bounded = min(total_task_attempts, verification_fix_cycles + 1)
        return max(1, bounded)

    def _git_status_snapshot(self, repo_root: Path) -> set[str]:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return set()
        return {line.rstrip() for line in result.stdout.splitlines() if line.strip()}

    def _assert_primary_workspace_unchanged(self, repo_root: Path, baseline: set[str]) -> None:
        current = self._git_status_snapshot(repo_root)
        if current != baseline:
            raise RuntimeError("Primary repository workspace changed during agent execution")

    def _modified_restricted_paths(self, worktree_path: Path, restricted_areas: list[str]) -> set[str]:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return set()

        restricted_hits: set[str] = set()
        for line in result.stdout.splitlines():
            if not line.strip() or len(line) < 4:
                continue
            path_part = line[3:]
            if " -> " in path_part:
                path_part = path_part.split(" -> ", 1)[1]
            normalized = path_part.strip().lstrip("./")
            segments = [segment.lower() for segment in normalized.split("/") if segment]
            for area in restricted_areas:
                marker = area.lower()
                if marker in segments:
                    restricted_hits.add(normalized)
                    break
        return restricted_hits

    def _git_diff(self, worktree_path: Path) -> str:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "diff", "--", "."],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ""
        return result.stdout
