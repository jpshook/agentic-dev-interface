"""Spec analysis and decomposition services for Phase 6."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adi.engine.artifact_store import ArtifactDocument, ArtifactStore
from adi.engine.config_loader import ConfigLoader
from adi.engine.run_manager import RunManager
from adi.engine.spec_planner import SpecAnalysis, SpecPlanner
from adi.engine.yaml_utils import load_yaml
from adi.engine.policy_evaluator import PolicyEvaluator
from adi.models.spec import (
    SPEC_EXECUTION_MODES,
    SpecArtifact,
    assert_spec_transition,
    validate_spec_frontmatter,
)
from adi.models.task import validate_task_frontmatter
from adi.services.backlog_service import BacklogService
from adi.services.task_service import TaskService
from adi.services.orchestrator_service import MultiRepoOrchestrator


class SpecService:
    """Spec lifecycle, analysis, decomposition, and execution orchestration."""

    def __init__(
        self,
        config_loader: ConfigLoader | None = None,
        artifact_store: ArtifactStore | None = None,
        planner: SpecPlanner | None = None,
        backlog_service: BacklogService | None = None,
        policy_evaluator: PolicyEvaluator | None = None,
        task_service: TaskService | None = None,
        orchestrator: MultiRepoOrchestrator | None = None,
    ) -> None:
        self.config_loader = config_loader or ConfigLoader()
        self.artifact_store = artifact_store or ArtifactStore()
        self.planner = planner or SpecPlanner()
        self.backlog_service = backlog_service or BacklogService(config_loader=self.config_loader)
        self.policy_evaluator = policy_evaluator or PolicyEvaluator()
        self.task_service = task_service or TaskService(config_loader=self.config_loader)
        self.orchestrator = orchestrator or MultiRepoOrchestrator(config_loader=self.config_loader)

    def create_spec(
        self,
        *,
        repo_ref: str,
        title: str,
        execution_mode: str = "manual",
        spec_id: str | None = None,
        priority: str = "medium",
    ) -> dict[str, Any]:
        repo = self._resolve_repo(repo_ref)
        repo_id = str(repo["id"])

        if execution_mode not in SPEC_EXECUTION_MODES:
            modes = ", ".join(sorted(SPEC_EXECUTION_MODES))
            raise ValueError(f"Unsupported execution mode '{execution_mode}'. Allowed: {modes}")

        resolved_id = spec_id or self._next_spec_id(repo_id)
        if self._find_spec_by_id(resolved_id) is not None:
            raise ValueError(f"Spec id already exists: {resolved_id}")

        spec_path = self.config_loader.repos_dir / repo_id / "specs" / f"{resolved_id}.md"
        frontmatter = {
            "id": resolved_id,
            "title": title,
            "repo_id": repo_id,
            "status": "draft",
            "priority": priority,
            "created_at": self._utc_now(),
            "updated_at": self._utc_now(),
            "execution_mode": execution_mode,
        }
        body = (
            f"# {title}\n\n"
            "## Problem\n\n"
            "Describe the problem.\n\n"
            "## Goals\n\n"
            "- Define target outcomes\n\n"
            "## Constraints\n\n"
            "- List non-negotiable constraints\n\n"
            "## Acceptance Criteria\n\n"
            "- Define observable checks\n"
        )
        self.artifact_store.write(
            spec_path,
            ArtifactDocument(frontmatter=frontmatter, body=body),
            validator=validate_spec_frontmatter,
        )

        return {
            "spec_id": resolved_id,
            "repo_id": repo_id,
            "path": str(spec_path),
            "status": "draft",
        }

    def analyze_spec(self, spec_id: str) -> dict[str, Any]:
        record = self._resolve_spec(spec_id)
        spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        if spec.status != "draft":
            raise ValueError(f"Spec must be in 'draft' state to analyze, got '{spec.status}'")

        repo_frontmatter = self._repo_frontmatter(spec.repo_id)
        repo_root = Path(str(record["repo"]["root"])).resolve()
        analysis = self.planner.analyze(
            spec_title=spec.title,
            spec_body=record["document"].body,
            repo_root=repo_root,
            repo_frontmatter=repo_frontmatter,
        )
        affected_repos = self._determine_affected_repos(
            spec=spec,
            spec_body=record["document"].body,
            analysis=analysis,
        )

        run_manager = RunManager(self.config_loader.runs_dir)
        run = run_manager.start_run(repo_id=spec.repo_id, task_id=spec.id, mode="spec-analyze")
        run_manager.write_metadata(
            run,
            {
                "run_id": run.id,
                "mode": "spec-analyze",
                "repo_id": spec.repo_id,
                "spec_id": spec.id,
                "status": "completed",
                "created_at": run.created_at,
                "finished_at": self._utc_now(),
                "analysis": analysis.to_dict(),
                "affected_repos": affected_repos,
            },
        )
        run_manager.write_summary(
            run,
            self._analysis_summary_markdown(spec_id=spec.id, analysis=analysis),
        )

        updated_body = self._replace_or_append_section(
            record["document"].body,
            "ADI Analysis",
            self.planner.render_analysis_markdown(analysis),
        )

        updated = self.artifact_store.update(
            record["path"],
            frontmatter_updates={
                "status": "analyzed",
                "updated_at": self._utc_now(),
                "analysis_summary": analysis.intent_summary,
                "ambiguity_count": len(analysis.ambiguities),
                "affected_repos": affected_repos,
                "last_analyzed_at": self._utc_now(),
            },
            body=updated_body,
            validator=validate_spec_frontmatter,
        )
        return {
            "spec_id": spec.id,
            "status": updated.frontmatter["status"],
            "analysis": analysis.to_dict(),
            "affected_repos": affected_repos,
            "run_id": run.id,
            "run_dir": str(run.dir),
        }

    def decompose_spec(self, spec_id: str) -> dict[str, Any]:
        record = self._resolve_spec(spec_id)
        spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        if spec.status != "analyzed":
            raise ValueError(f"Spec must be in 'analyzed' state to decompose, got '{spec.status}'")

        repo_frontmatter = self._repo_frontmatter(spec.repo_id)
        repo_root = Path(str(record["repo"]["root"])).resolve()
        analysis = self.planner.analyze(
            spec_title=spec.title,
            spec_body=record["document"].body,
            repo_root=repo_root,
            repo_frontmatter=repo_frontmatter,
        )

        plans = self.planner.decompose(
            analysis=analysis,
            repo_frontmatter=repo_frontmatter,
            default_priority=str(spec.priority).lower(),
        )

        if not plans:
            raise ValueError("No tasks generated from spec decomposition")
        affected_repos = self._affected_repos_from_spec(spec=spec, fallback=[spec.repo_id])
        created_tasks = self._write_generated_tasks(
            spec=spec,
            plans=plans,
            analysis=analysis,
            affected_repos=affected_repos,
        )

        run_manager = RunManager(self.config_loader.runs_dir)
        run = run_manager.start_run(repo_id=spec.repo_id, task_id=spec.id, mode="spec-decompose")
        run_manager.write_metadata(
            run,
            {
                "run_id": run.id,
                "mode": "spec-decompose",
                "repo_id": spec.repo_id,
                "spec_id": spec.id,
                "status": "completed",
                "created_at": run.created_at,
                "finished_at": self._utc_now(),
                "generated_task_ids": [task["id"] for task in created_tasks],
                "analysis": analysis.to_dict(),
                "affected_repos": affected_repos,
            },
        )

        decomposition_section = self.planner.render_decomposition_markdown(
            created_tasks,
            analysis.open_questions,
        )
        updated_body = self._replace_or_append_section(
            record["document"].body,
            "ADI Decomposition",
            decomposition_section,
        )

        updated = self.artifact_store.update(
            record["path"],
            frontmatter_updates={
                "status": "decomposed",
                "updated_at": self._utc_now(),
                "decomposed_task_ids": [task["id"] for task in created_tasks],
                "generated_high_risk_count": len(
                    [task for task in created_tasks if str(task.get("risk", "")) == "high"]
                ),
                "affected_repos": affected_repos,
                "last_decomposed_at": self._utc_now(),
            },
            body=updated_body,
            validator=validate_spec_frontmatter,
        )

        run_manager.write_summary(
            run,
            self._decomposition_summary_markdown(spec.id, created_tasks),
        )

        return {
            "spec_id": spec.id,
            "status": updated.frontmatter["status"],
            "generated_tasks": created_tasks,
            "affected_repos": affected_repos,
            "run_id": run.id,
            "run_dir": str(run.dir),
        }

    def approve_spec(self, spec_id: str) -> dict[str, Any]:
        record = self._resolve_spec(spec_id)
        spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        assert_spec_transition(spec.status, "approved")

        linked = self._linked_tasks(spec.id)
        approved_task_ids: list[str] = []

        for item in linked:
            frontmatter = item["document"].frontmatter
            if str(frontmatter.get("status", "")) != "proposed":
                continue
            updated = self.artifact_store.update(
                item["path"],
                frontmatter_updates={
                    "status": "approved",
                    "updated_at": self._utc_now(),
                },
                validator=validate_task_frontmatter,
            )
            approved_task_ids.append(str(updated.frontmatter["id"]))

        updated_spec = self.artifact_store.update(
            record["path"],
            frontmatter_updates={
                "status": "approved",
                "updated_at": self._utc_now(),
                "approved_at": self._utc_now(),
            },
            validator=validate_spec_frontmatter,
        )

        return {
            "spec_id": spec.id,
            "status": updated_spec.frontmatter["status"],
            "approved_task_ids": approved_task_ids,
        }

    def delete_spec(self, spec_id: str) -> dict[str, Any]:
        record = self._resolve_spec(spec_id)
        spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        linked = self._linked_tasks(spec.id)
        deleted_tasks: list[dict[str, Any]] = []
        for item in linked:
            task_id = str(item["document"].frontmatter.get("id", "")).strip()
            if not task_id:
                continue
            deleted_tasks.append(self.task_service.delete_task(task_id))

        deleted_run_dirs = self._delete_spec_runs(spec.id)

        if record["path"].exists():
            record["path"].unlink()

        return {
            "spec_id": spec.id,
            "repo_id": spec.repo_id,
            "deleted": True,
            "path": str(record["path"]),
            "deleted_task_ids": [str(item["task_id"]) for item in deleted_tasks],
            "deleted_run_dirs": deleted_run_dirs,
        }

    def spec_status(self, spec_id: str) -> dict[str, Any]:
        record = self._resolve_spec(spec_id)
        spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        linked = self._linked_tasks(spec.id)
        counts: dict[str, int] = {}
        repo_breakdown: dict[str, dict[str, int]] = {}
        for item in linked:
            repo_id = str(item["repo"].get("id", ""))
            status = str(item["document"].frontmatter.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1
            bucket = repo_breakdown.setdefault(repo_id, {"total": 0})
            bucket["total"] += 1
            bucket[status] = bucket.get(status, 0) + 1

        repos_involved = self._affected_repos_from_spec(
            spec=spec,
            fallback=sorted({str(item["repo"].get("id", "")) for item in linked if item.get("repo")}),
        )

        return {
            "spec": {
                "id": spec.id,
                "title": spec.title,
                "repo_id": spec.repo_id,
                "status": spec.status,
                "priority": spec.priority,
                "execution_mode": spec.execution_mode,
                "path": str(record["path"]),
            },
            "summary": {
                "repos_involved": len(repos_involved),
                "tasks_total": len(linked),
                "running": counts.get("in_progress", 0) + counts.get("pending_verification", 0),
                "completed": counts.get("completed", 0),
                "blocked": counts.get("blocked", 0),
                "failed": counts.get("failed", 0),
                "approved": counts.get("approved", 0),
                "proposed": counts.get("proposed", 0),
            },
            "repos": repos_involved,
            "linked_tasks": {
                "count": len(linked),
                "by_status": counts,
                "task_ids": [str(item["document"].frontmatter.get("id", "")) for item in linked],
                "by_repo": repo_breakdown,
            },
        }

    def spec_repos(self, spec_id: str) -> dict[str, Any]:
        record = self._resolve_spec(spec_id)
        spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)
        linked = self._linked_tasks(spec.id)

        linked_repos = sorted(
            {
                str(item["repo"].get("id", ""))
                for item in linked
                if str(item["repo"].get("id", ""))
            }
        )
        affected = self._affected_repos_from_spec(spec=spec, fallback=linked_repos or [spec.repo_id])

        return {
            "spec_id": spec.id,
            "status": spec.status,
            "affected_repos": affected,
            "linked_repos": linked_repos,
            "linked_task_count": len(linked),
        }

    def run_spec(
        self,
        spec_id: str,
        *,
        max_tasks: int | None = None,
        time_limit_seconds: int | None = None,
    ) -> dict[str, Any]:
        record = self._resolve_spec(spec_id)
        spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        actions: list[str] = []

        if spec.status == "draft":
            self.analyze_spec(spec.id)
            actions.append("analyzed")
            record = self._resolve_spec(spec.id)
            spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        if spec.status == "analyzed":
            self.decompose_spec(spec.id)
            actions.append("decomposed")
            record = self._resolve_spec(spec.id)
            spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        if spec.execution_mode == "manual":
            return {
                "spec_id": spec.id,
                "status": spec.status,
                "execution_mode": spec.execution_mode,
                "actions": actions,
                "backlog_started": False,
                "requires_human_input": False,
                "message": "Manual mode: analysis/decomposition completed without execution",
            }

        if spec.execution_mode == "approval_required" and spec.status != "approved":
            return {
                "spec_id": spec.id,
                "status": spec.status,
                "execution_mode": spec.execution_mode,
                "actions": actions,
                "backlog_started": False,
                "requires_human_input": False,
                "message": "Spec requires approval before execution",
            }

        linked_before = self._linked_tasks(spec.id)
        safety_check = self._spec_execution_safety_check(
            spec_record=record,
            spec=spec,
            linked_tasks=linked_before,
        )
        if not safety_check["ok"]:
            return {
                "spec_id": spec.id,
                "status": spec.status,
                "execution_mode": spec.execution_mode,
                "actions": actions,
                "backlog_started": False,
                "requires_human_input": True,
                "safety_reasons": safety_check["reasons"],
                "message": "Execution paused pending human input",
            }

        if spec.execution_mode == "auto_safe" and spec.status == "decomposed":
            self.approve_spec(spec.id)
            actions.append("approved")
            record = self._resolve_spec(spec.id)
            spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        if spec.status == "approved":
            self._transition_spec(record["path"], target="in_progress")
            actions.append("in_progress")
            record = self._resolve_spec(spec.id)
            spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        linked_task_records = self._linked_tasks(spec.id)
        if not linked_task_records:
            raise ValueError("Spec has no linked tasks to execute")

        orchestration_tasks = [dict(item["document"].frontmatter) for item in linked_task_records]
        orchestration_result = self.orchestrator.run(
            spec_id=spec.id,
            tasks=orchestration_tasks,
            task_runner=self.task_service.run_task,
            max_tasks=max_tasks,
            time_limit_seconds=time_limit_seconds,
        )
        actions.append("orchestrated")

        linked_after = self._linked_tasks(spec.id)
        statuses = [str(item["document"].frontmatter.get("status", "")) for item in linked_after]
        if statuses and all(status == "completed" for status in statuses):
            self._transition_spec(record["path"], target="completed")
            actions.append("completed")
        elif any(status == "failed" for status in statuses):
            self._transition_spec(record["path"], target="blocked")
            actions.append("blocked")

        latest = self._resolve_spec(spec.id)
        latest_spec = SpecArtifact.from_frontmatter(latest["document"].frontmatter)

        return {
            "spec_id": latest_spec.id,
            "status": latest_spec.status,
            "execution_mode": latest_spec.execution_mode,
            "actions": actions,
            "backlog_started": True,
            "requires_human_input": False,
            "orchestration": orchestration_result,
            "backlog_run": orchestration_result,
        }

    def _write_generated_tasks(
        self,
        *,
        spec: SpecArtifact,
        plans: list[Any],
        analysis: SpecAnalysis,
        affected_repos: list[str],
    ) -> list[dict[str, Any]]:
        if not affected_repos:
            affected_repos = [spec.repo_id]

        existing_ids = self._existing_task_ids()
        generated: list[dict[str, Any]] = []
        source_items = analysis.acceptance_criteria or analysis.goals or [analysis.intent_summary]

        repo_frontmatter_map = {repo_id: self._repo_frontmatter(repo_id) for repo_id in affected_repos}
        repo_roles = {
            repo_id: self._repo_role(repo_id, repo_frontmatter_map.get(repo_id, {}))
            for repo_id in affected_repos
        }

        for index, item in enumerate(source_items, start=1):
            target_repo = self._select_repo_for_item(
                item=item,
                affected_repos=affected_repos,
                repo_roles=repo_roles,
            )
            target_repo_frontmatter = repo_frontmatter_map.get(target_repo, {})
            item_analysis = SpecAnalysis(
                goals=[item],
                constraints=analysis.constraints,
                acceptance_criteria=[item],
                non_goals=analysis.non_goals,
                open_questions=analysis.open_questions,
                ambiguities=analysis.ambiguities,
                likely_areas=analysis.likely_areas,
                intent_summary=analysis.intent_summary,
            )
            item_plans = self.planner.decompose(
                analysis=item_analysis,
                repo_frontmatter=target_repo_frontmatter,
                default_priority=str(spec.priority).lower(),
            )
            plan = item_plans[0] if item_plans else plans[min(index - 1, len(plans) - 1)]

            task_id = self._next_task_id(
                spec_id=spec.id,
                repo_id=target_repo,
                ordinal=index,
                existing_ids=existing_ids,
            )
            existing_ids.add(task_id)

            tasks_dir = self.config_loader.repos_dir / target_repo / "tasks"
            tasks_dir.mkdir(parents=True, exist_ok=True)

            frontmatter = {
                "id": task_id,
                "title": plan.title,
                "repo_id": target_repo,
                "status": "proposed",
                "priority": plan.priority,
                "size": plan.size,
                "risk": plan.risk,
                "created_at": self._utc_now(),
                "updated_at": self._utc_now(),
                "depends_on": [],
                "acceptance_checks": plan.acceptance_checks,
                "spec_id": spec.id,
                "labels": plan.labels,
            }
            body = (
                f"# Task {task_id}\n\n"
                f"{plan.description}\n\n"
                "## Acceptance Criteria\n\n"
                + "\n".join(f"- {item}" for item in plan.acceptance_checks)
                + "\n"
            )
            path = tasks_dir / f"{task_id}.md"
            self.artifact_store.write(
                path,
                ArtifactDocument(frontmatter=frontmatter, body=body),
                validator=validate_task_frontmatter,
            )

            generated.append(
                {
                    "id": task_id,
                    "title": plan.title,
                    "repo_id": target_repo,
                    "priority": plan.priority,
                    "size": plan.size,
                    "risk": plan.risk,
                    "depends_on": [],
                    "acceptance_checks": plan.acceptance_checks,
                    "path": str(path),
                    "category": plan.labels[0] if plan.labels else "implementation",
                }
            )

        # Assign deterministic dependencies: tests follow repo implementation, frontend follows backend/shared.
        last_non_test_by_repo: dict[str, str] = {}
        seed_backend_or_shared: list[str] = []
        for task in generated:
            category = str(task.get("category", ""))
            repo_id = str(task.get("repo_id", ""))
            role = repo_roles.get(repo_id, "general")
            if category != "tests":
                last_non_test_by_repo[repo_id] = str(task["id"])
                if role in {"backend", "shared"}:
                    seed_backend_or_shared.append(str(task["id"]))

        for task in generated:
            deps: list[str] = []
            repo_id = str(task.get("repo_id", ""))
            role = repo_roles.get(repo_id, "general")
            category = str(task.get("category", ""))
            if category == "tests":
                seed = last_non_test_by_repo.get(repo_id)
                if seed and seed != task["id"]:
                    deps.append(seed)
            if role == "frontend" and seed_backend_or_shared:
                seed = seed_backend_or_shared[0]
                if seed != task["id"] and seed not in deps:
                    deps.append(seed)

            if deps:
                task["depends_on"] = deps
                self.artifact_store.update(
                    Path(str(task["path"])),
                    frontmatter_updates={
                        "depends_on": deps,
                        "updated_at": self._utc_now(),
                    },
                    validator=validate_task_frontmatter,
                )

        for task in generated:
            task.pop("category", None)
        return generated

    def _transition_spec(self, path: Path, target: str) -> None:
        current = str(self.artifact_store.read(path).frontmatter.get("status", ""))
        assert_spec_transition(current, target)
        self.artifact_store.update(
            path,
            frontmatter_updates={
                "status": target,
                "updated_at": self._utc_now(),
            },
            validator=validate_spec_frontmatter,
        )

    def _resolve_spec(self, spec_id: str) -> dict[str, Any]:
        found = self._find_spec_by_id(spec_id)
        if found is None:
            raise ValueError(f"Unknown spec: {spec_id}")
        return found

    def _find_spec_by_id(self, spec_id: str) -> dict[str, Any] | None:
        repos = self.config_loader.load_repos_registry()
        match: dict[str, Any] | None = None
        for repo in repos:
            repo_id = str(repo.get("id", ""))
            specs_dir = self.config_loader.repos_dir / repo_id / "specs"
            if not specs_dir.exists():
                continue
            for path in specs_dir.glob("*.md"):
                document = self.artifact_store.read(path)
                if str(document.frontmatter.get("id", "")) != spec_id:
                    continue
                validate_spec_frontmatter(document.frontmatter)
                if match is not None:
                    raise ValueError(f"Ambiguous spec id '{spec_id}' across repositories")
                match = {
                    "repo": repo,
                    "path": path,
                    "document": document,
                }
        return match

    def _linked_tasks(self, spec_id: str) -> list[dict[str, Any]]:
        linked: list[dict[str, Any]] = []
        for repo in self.config_loader.load_repos_registry():
            repo_id = str(repo.get("id", ""))
            tasks_dir = self.config_loader.repos_dir / repo_id / "tasks"
            if not tasks_dir.exists():
                continue
            for path in tasks_dir.glob("*.md"):
                document = self.artifact_store.read(path)
                if str(document.frontmatter.get("spec_id", "")) != spec_id:
                    continue
                linked.append({"repo": repo, "path": path, "document": document})
        return linked

    def _delete_spec_runs(self, spec_id: str) -> list[str]:
        deleted: list[str] = []
        if not self.config_loader.runs_dir.exists():
            return deleted

        for run_dir in self.config_loader.runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            metadata_path = run_dir / "metadata.yaml"
            if not metadata_path.exists():
                continue
            payload = load_yaml(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            if str(payload.get("spec_id", "")) != spec_id:
                continue
            shutil.rmtree(run_dir, ignore_errors=True)
            deleted.append(str(run_dir))
        return deleted

    def _repo_frontmatter(self, repo_id: str) -> dict[str, Any]:
        path = self.config_loader.repos_dir / repo_id / "repo.md"
        if not path.exists():
            return {}
        return self.artifact_store.read(path).frontmatter

    def _affected_repos_from_spec(self, *, spec: SpecArtifact, fallback: list[str]) -> list[str]:
        repos_index = {str(repo.get("id", "")) for repo in self.config_loader.load_repos_registry()}
        raw = spec.extras.get("affected_repos", [])
        selected: list[str] = []
        if isinstance(raw, list):
            for item in raw:
                repo_id = str(item).strip()
                if repo_id and repo_id in repos_index and repo_id not in selected:
                    selected.append(repo_id)
        if spec.repo_id not in selected and spec.repo_id in repos_index:
            selected.insert(0, spec.repo_id)
        if not selected:
            for repo_id in fallback:
                normalized = str(repo_id).strip()
                if normalized and normalized in repos_index and normalized not in selected:
                    selected.append(normalized)
        if not selected:
            selected.append(spec.repo_id)
        return selected

    def _determine_affected_repos(
        self,
        *,
        spec: SpecArtifact,
        spec_body: str,
        analysis: SpecAnalysis,
    ) -> list[str]:
        repos = self.config_loader.load_repos_registry()
        if not repos:
            return [spec.repo_id]

        index = {str(repo.get("id", "")): repo for repo in repos}
        text = f"{spec.title}\n{spec_body}\n{' '.join(analysis.likely_areas)}".lower()
        selected: list[str] = []

        # Start with explicit references to repo id/name in the spec text.
        for repo_id, entry in index.items():
            name = str(entry.get("name", "")).lower()
            if repo_id.lower() in text or (name and name in text):
                if repo_id not in selected:
                    selected.append(repo_id)

        # Infer from capability/role cues.
        needs_frontend = any(marker in text for marker in ["ui", "frontend", "web", "client"])
        needs_backend = any(marker in text for marker in ["api", "backend", "service", "endpoint"])
        needs_shared = any(marker in text for marker in ["shared", "schema", "types", "library"])
        needs_infra = any(marker in text for marker in ["infra", "deployment", "ops", "k8s", "docker"])

        for repo_id in index:
            role = self._repo_role(repo_id, self._repo_frontmatter(repo_id))
            if needs_frontend and role == "frontend" and repo_id not in selected:
                selected.append(repo_id)
            if needs_backend and role == "backend" and repo_id not in selected:
                selected.append(repo_id)
            if needs_shared and role == "shared" and repo_id not in selected:
                selected.append(repo_id)
            if needs_infra and role == "infra" and repo_id not in selected:
                selected.append(repo_id)

        if spec.repo_id not in selected:
            selected.insert(0, spec.repo_id)
        return selected

    def _repo_role(self, repo_id: str, frontmatter: dict[str, Any]) -> str:
        text_parts = [repo_id.lower(), str(frontmatter.get("name", "")).lower()]
        stack = frontmatter.get("stack", [])
        if isinstance(stack, list):
            text_parts.extend(str(item).lower() for item in stack)
        language = str(frontmatter.get("language", "")).lower()
        if language:
            text_parts.append(language)
        text = " ".join(text_parts)

        if any(marker in text for marker in ["web", "frontend", "ui", "react", "vue", "svelte", "next"]):
            return "frontend"
        if any(marker in text for marker in ["api", "backend", "service", "server"]):
            return "backend"
        if any(marker in text for marker in ["shared", "common", "types", "library", "sdk"]):
            return "shared"
        if any(marker in text for marker in ["infra", "deploy", "ops", "terraform", "k8s"]):
            return "infra"
        return "general"

    def _select_repo_for_item(
        self,
        *,
        item: str,
        affected_repos: list[str],
        repo_roles: dict[str, str],
    ) -> str:
        lower = item.lower()

        for repo_id in affected_repos:
            if repo_id.lower() in lower:
                return repo_id

        if any(marker in lower for marker in ["ui", "frontend", "screen", "component", "web"]):
            candidates = [repo for repo in affected_repos if repo_roles.get(repo) == "frontend"]
            if candidates:
                return candidates[0]
        if any(marker in lower for marker in ["api", "endpoint", "server", "backend"]):
            candidates = [repo for repo in affected_repos if repo_roles.get(repo) == "backend"]
            if candidates:
                return candidates[0]
        if any(marker in lower for marker in ["shared", "schema", "types", "library"]):
            candidates = [repo for repo in affected_repos if repo_roles.get(repo) == "shared"]
            if candidates:
                return candidates[0]
        if any(marker in lower for marker in ["infra", "deploy", "ops", "k8s", "docker"]):
            candidates = [repo for repo in affected_repos if repo_roles.get(repo) == "infra"]
            if candidates:
                return candidates[0]

        # Prefer non-frontend repos for test/verification heavy work unless no option exists.
        if any(marker in lower for marker in ["test", "verify", "coverage"]):
            candidates = [
                repo
                for repo in affected_repos
                if repo_roles.get(repo) in {"backend", "shared", "general"}
            ]
            if candidates:
                return candidates[0]

        return affected_repos[0]

    def _resolve_repo(self, repo_ref: str) -> dict[str, Any]:
        repos = self.config_loader.load_repos_registry()
        for repo in repos:
            if repo_ref in {repo.get("id"), repo.get("name")}:
                return repo
        raise ValueError(f"Unknown repo: {repo_ref}")

    def _next_spec_id(self, repo_id: str) -> str:
        specs_dir = self.config_loader.repos_dir / repo_id / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        existing: set[str] = set()
        for path in specs_dir.glob("*.md"):
            document = self.artifact_store.read(path)
            spec_id = str(document.frontmatter.get("id", "")).strip()
            if spec_id:
                existing.add(spec_id)

        index = 1
        while True:
            candidate = f"SP-{index:03d}"
            if candidate not in existing:
                return candidate
            index += 1

    def _existing_task_ids(self) -> set[str]:
        ids: set[str] = set()
        for repo in self.config_loader.load_repos_registry():
            repo_id = str(repo.get("id", ""))
            tasks_dir = self.config_loader.repos_dir / repo_id / "tasks"
            if not tasks_dir.exists():
                continue
            for path in tasks_dir.glob("*.md"):
                doc = self.artifact_store.read(path)
                task_id = str(doc.frontmatter.get("id", "")).strip()
                if task_id:
                    ids.add(task_id)
        return ids

    def _next_task_id(
        self,
        *,
        spec_id: str,
        repo_id: str,
        ordinal: int,
        existing_ids: set[str],
    ) -> str:
        spec_part = re.sub(r"[^A-Za-z0-9]+", "-", spec_id).strip("-").upper() or "SPEC"
        repo_part = re.sub(r"[^A-Za-z0-9]+", "-", repo_id).strip("-").upper() or "REPO"
        counter = ordinal
        while True:
            candidate = f"TK-{spec_part}-{repo_part}-{counter:03d}"
            if candidate not in existing_ids:
                return candidate
            counter += 1

    def _replace_or_append_section(self, body: str, section_label: str, replacement: str) -> str:
        pattern = re.compile(
            rf"(?ms)^## {re.escape(section_label)}\n.*?(?=^## |\Z)",
        )
        cleaned = pattern.sub("", body).rstrip()
        if cleaned:
            return f"{cleaned}\n\n{replacement.strip()}\n"
        return f"{replacement.strip()}\n"

    def _analysis_summary_markdown(self, spec_id: str, analysis: SpecAnalysis) -> str:
        return (
            f"# Spec Analysis {spec_id}\n\n"
            f"- Intent: {analysis.intent_summary}\n"
            f"- Implementation scope: {', '.join(analysis.likely_areas)}\n"
            f"- Goals: {len(analysis.goals)}\n"
            f"- Constraints: {len(analysis.constraints)}\n"
            f"- Acceptance criteria: {len(analysis.acceptance_criteria)}\n"
            f"- Ambiguities: {len(analysis.ambiguities)}\n"
        )

    def _decomposition_summary_markdown(self, spec_id: str, tasks: list[dict[str, Any]]) -> str:
        lines = [
            f"# Spec Decomposition {spec_id}",
            "",
            f"- Generated tasks: {len(tasks)}",
            "",
            "## Tasks",
            "",
        ]
        for task in tasks:
            lines.append(f"- `{task['id']}` {task['title']}")
        lines.append("")
        return "\n".join(lines)

    def _utc_now(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    def _spec_execution_safety_check(
        self,
        *,
        spec_record: dict[str, Any],
        spec: SpecArtifact,
        linked_tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        reasons: list[str] = []

        ambiguity_count = int(spec_record["document"].frontmatter.get("ambiguity_count", 0))
        if ambiguity_count > 0:
            reasons.append(f"Spec has unresolved ambiguities ({ambiguity_count})")

        if not linked_tasks:
            reasons.append("Spec has no generated tasks")
            return {"ok": False, "reasons": reasons}

        effective = self.config_loader.load_effective_config(repo_id=spec.repo_id)
        policy_cfg = effective.get("policies", {}).get("policy", {})
        auto_cfg = policy_cfg.get("auto_execute", {})
        restricted_areas = [str(item).lower() for item in policy_cfg.get("restricted_areas", [])]

        for item in linked_tasks:
            frontmatter = item["document"].frontmatter
            task_id = str(frontmatter.get("id", ""))
            title = str(frontmatter.get("title", ""))
            size = str(frontmatter.get("size", "small"))
            risk = str(frontmatter.get("risk", "low"))

            if risk == "high":
                reasons.append(f"Task {task_id} is high risk")

            touches_restricted = self._task_touches_restricted_area(frontmatter, restricted_areas)
            if touches_restricted:
                reasons.append(f"Task {task_id} touches protected area")

            decision = self.policy_evaluator.evaluate(
                risk=risk,
                size=size,
                dependencies_satisfied=True,
                touches_restricted_area=touches_restricted,
                auto_max_risk=str(auto_cfg.get("max_risk", "low")),
                auto_max_size=str(auto_cfg.get("max_size", "small")),
            )
            if decision.action != "auto_execute":
                reasons.append(
                    f"Task {task_id} requires manual decision ({decision.action})"
                )

            if not title:
                reasons.append(f"Task {task_id} is missing title")

        deduped = []
        seen: set[str] = set()
        for reason in reasons:
            if reason in seen:
                continue
            seen.add(reason)
            deduped.append(reason)
        return {"ok": not deduped, "reasons": deduped}

    def _task_touches_restricted_area(
        self,
        frontmatter: dict[str, Any],
        restricted_areas: list[str],
    ) -> bool:
        title = str(frontmatter.get("title", "")).lower()
        labels: list[str] = []
        for key in ["labels", "tags"]:
            value = frontmatter.get(key, [])
            if isinstance(value, list):
                labels.extend(str(item).lower() for item in value)
        for area in restricted_areas:
            if area in title:
                return True
            if area in labels:
                return True
        return False
