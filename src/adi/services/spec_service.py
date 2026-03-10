"""Spec analysis and decomposition services for Phase 6."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adi.engine.artifact_store import ArtifactDocument, ArtifactStore
from adi.engine.config_loader import ConfigLoader
from adi.engine.run_manager import RunManager
from adi.engine.spec_planner import SpecAnalysis, SpecPlanner
from adi.models.spec import (
    SPEC_EXECUTION_MODES,
    SpecArtifact,
    assert_spec_transition,
    validate_spec_frontmatter,
)
from adi.models.task import validate_task_frontmatter
from adi.services.backlog_service import BacklogService


class SpecService:
    """Spec lifecycle, analysis, decomposition, and execution orchestration."""

    def __init__(
        self,
        config_loader: ConfigLoader | None = None,
        artifact_store: ArtifactStore | None = None,
        planner: SpecPlanner | None = None,
        backlog_service: BacklogService | None = None,
    ) -> None:
        self.config_loader = config_loader or ConfigLoader()
        self.artifact_store = artifact_store or ArtifactStore()
        self.planner = planner or SpecPlanner()
        self.backlog_service = backlog_service or BacklogService(config_loader=self.config_loader)

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
                "last_analyzed_at": self._utc_now(),
            },
            body=updated_body,
            validator=validate_spec_frontmatter,
        )
        return {
            "spec_id": spec.id,
            "status": updated.frontmatter["status"],
            "analysis": analysis.to_dict(),
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

        created_tasks = self._write_generated_tasks(spec=spec, plans=plans)

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

    def spec_status(self, spec_id: str) -> dict[str, Any]:
        record = self._resolve_spec(spec_id)
        spec = SpecArtifact.from_frontmatter(record["document"].frontmatter)

        linked = self._linked_tasks(spec.id)
        counts: dict[str, int] = {}
        for item in linked:
            status = str(item["document"].frontmatter.get("status", "unknown"))
            counts[status] = counts.get(status, 0) + 1

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
            "linked_tasks": {
                "count": len(linked),
                "by_status": counts,
                "task_ids": [str(item["document"].frontmatter.get("id", "")) for item in linked],
            },
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
                "message": "Manual mode: analysis/decomposition completed without execution",
            }

        if spec.execution_mode == "approval_required" and spec.status != "approved":
            return {
                "spec_id": spec.id,
                "status": spec.status,
                "execution_mode": spec.execution_mode,
                "actions": actions,
                "backlog_started": False,
                "message": "Spec requires approval before execution",
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

        linked_task_ids = [
            str(item["document"].frontmatter.get("id", ""))
            for item in self._linked_tasks(spec.id)
            if str(item["document"].frontmatter.get("id", ""))
        ]

        if not linked_task_ids:
            raise ValueError("Spec has no linked tasks to execute")

        backlog_result = self.backlog_service.run(
            repo_ref=spec.repo_id,
            max_tasks=max_tasks,
            time_limit_seconds=time_limit_seconds,
            include_task_ids=set(linked_task_ids),
        )
        actions.append("backlog_run")

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
            "backlog_run": backlog_result["backlog_run"],
        }

    def _write_generated_tasks(self, spec: SpecArtifact, plans: list[Any]) -> list[dict[str, Any]]:
        repo_id = spec.repo_id
        tasks_dir = self.config_loader.repos_dir / repo_id / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)

        existing_ids = self._existing_task_ids(repo_id)
        generated: list[dict[str, Any]] = []

        for index, plan in enumerate(plans, start=1):
            task_id = self._next_task_id(spec_id=spec.id, ordinal=index, existing_ids=existing_ids)
            existing_ids.add(task_id)

            depends_on = [
                generated[dep_index]["id"]
                for dep_index in plan.depends_on_indexes
                if 0 <= dep_index < len(generated)
            ]

            frontmatter = {
                "id": task_id,
                "title": plan.title,
                "repo_id": repo_id,
                "status": "proposed",
                "priority": plan.priority,
                "size": plan.size,
                "risk": plan.risk,
                "created_at": self._utc_now(),
                "updated_at": self._utc_now(),
                "depends_on": depends_on,
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
                    "priority": plan.priority,
                    "size": plan.size,
                    "risk": plan.risk,
                    "depends_on": depends_on,
                    "acceptance_checks": plan.acceptance_checks,
                    "path": str(path),
                }
            )

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

    def _repo_frontmatter(self, repo_id: str) -> dict[str, Any]:
        path = self.config_loader.repos_dir / repo_id / "repo.md"
        if not path.exists():
            return {}
        return self.artifact_store.read(path).frontmatter

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

    def _existing_task_ids(self, repo_id: str) -> set[str]:
        tasks_dir = self.config_loader.repos_dir / repo_id / "tasks"
        if not tasks_dir.exists():
            return set()
        ids: set[str] = set()
        for path in tasks_dir.glob("*.md"):
            doc = self.artifact_store.read(path)
            task_id = str(doc.frontmatter.get("id", "")).strip()
            if task_id:
                ids.add(task_id)
        return ids

    def _next_task_id(self, *, spec_id: str, ordinal: int, existing_ids: set[str]) -> str:
        spec_part = re.sub(r"[^A-Za-z0-9]+", "-", spec_id).strip("-").upper() or "SPEC"
        counter = ordinal
        while True:
            candidate = f"TK-{spec_part}-{counter:03d}"
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
