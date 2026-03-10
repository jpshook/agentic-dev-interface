"""Deterministic spec analysis and task decomposition."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SpecAnalysis:
    """Normalized spec analysis output."""

    goals: list[str]
    constraints: list[str]
    acceptance_criteria: list[str]
    non_goals: list[str]
    open_questions: list[str]
    ambiguities: list[str]
    likely_areas: list[str]
    intent_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "goals": self.goals,
            "constraints": self.constraints,
            "acceptance_criteria": self.acceptance_criteria,
            "non_goals": self.non_goals,
            "open_questions": self.open_questions,
            "ambiguities": self.ambiguities,
            "likely_areas": self.likely_areas,
            "intent_summary": self.intent_summary,
            "implementation_scope": self.likely_areas,
            "system_components": self.likely_areas,
            "task_boundaries": self.acceptance_criteria or self.goals,
        }


@dataclass(slots=True)
class TaskPlan:
    """Generated task plan entry before writing artifacts."""

    title: str
    description: str
    priority: str
    size: str
    risk: str
    depends_on_indexes: list[int]
    acceptance_checks: list[str]
    labels: list[str]


class SpecPlanner:
    """Deterministic planner for spec analysis and decomposition."""

    def analyze(
        self,
        *,
        spec_title: str,
        spec_body: str,
        repo_root: Path,
        repo_frontmatter: dict[str, Any],
    ) -> SpecAnalysis:
        sections = self._extract_sections(spec_body)

        goals = self._items_from_sections(sections, ["goal", "objectives", "intent"])
        constraints = self._items_from_sections(sections, ["constraint", "limits"])
        acceptance = self._items_from_sections(
            sections,
            ["acceptance", "acceptance criteria", "criteria"],
        )
        non_goals = self._items_from_sections(sections, ["non-goal", "non goal", "out of scope"])
        open_questions = self._items_from_sections(
            sections,
            ["open question", "questions", "ambiguity"],
        )

        if not goals:
            goals = self._fallback_items(spec_body)

        ambiguities = self._find_ambiguities(spec_body)
        likely_areas = self._likely_areas(
            text=f"{spec_title}\n{spec_body}",
            repo_root=repo_root,
            repo_frontmatter=repo_frontmatter,
        )

        intent_summary = self._summarize_intent(
            spec_title=spec_title,
            goals=goals,
            constraints=constraints,
            acceptance=acceptance,
            likely_areas=likely_areas,
            ambiguities=ambiguities,
        )

        return SpecAnalysis(
            goals=goals,
            constraints=constraints,
            acceptance_criteria=acceptance,
            non_goals=non_goals,
            open_questions=open_questions,
            ambiguities=ambiguities,
            likely_areas=likely_areas,
            intent_summary=intent_summary,
        )

    def decompose(
        self,
        *,
        analysis: SpecAnalysis,
        repo_frontmatter: dict[str, Any],
        default_priority: str,
    ) -> list[TaskPlan]:
        source_items = analysis.acceptance_criteria or analysis.goals
        if not source_items:
            source_items = [analysis.intent_summary]

        commands = repo_frontmatter.get("commands", {})
        command_map = commands if isinstance(commands, dict) else {}

        plans: list[TaskPlan] = []
        for item in source_items:
            category = self._classify_item(item)
            priority = self._task_priority(item, default_priority)
            size = self._task_size(item)
            risk = self._task_risk(item)
            title = self._task_title(item, category)
            description = self._task_description(item, category, analysis)
            acceptance_checks = self._acceptance_checks_for_category(category, command_map)
            labels = [category]
            if risk in {"medium", "high"}:
                labels.append("risk")

            plans.append(
                TaskPlan(
                    title=title,
                    description=description,
                    priority=priority,
                    size=size,
                    risk=risk,
                    depends_on_indexes=[],
                    acceptance_checks=acceptance_checks,
                    labels=labels,
                )
            )

        self._assign_dependencies(plans)
        return plans

    def render_analysis_markdown(self, analysis: SpecAnalysis) -> str:
        lines = [
            "## ADI Analysis",
            "",
            f"Intent summary: {analysis.intent_summary}",
            "",
            "### Goals",
            "",
        ]
        lines.extend(self._markdown_list(analysis.goals))
        lines.extend(["", "### Constraints", ""])
        lines.extend(self._markdown_list(analysis.constraints))
        lines.extend(["", "### Acceptance Criteria", ""])
        lines.extend(self._markdown_list(analysis.acceptance_criteria))
        lines.extend(["", "### Non-Goals", ""])
        lines.extend(self._markdown_list(analysis.non_goals))
        lines.extend(["", "### Open Questions", ""])
        lines.extend(self._markdown_list(analysis.open_questions))
        lines.extend(["", "### Ambiguities", ""])
        lines.extend(self._markdown_list(analysis.ambiguities))
        lines.extend(["", "### Likely Areas", ""])
        lines.extend(self._markdown_list(analysis.likely_areas))
        lines.append("")
        return "\n".join(lines)

    def render_decomposition_markdown(self, tasks: list[dict[str, Any]], open_questions: list[str]) -> str:
        lines = [
            "## ADI Decomposition",
            "",
            "### Generated Tasks",
            "",
        ]
        for task in tasks:
            deps = task.get("depends_on", [])
            dep_text = ", ".join(deps) if deps else "none"
            checks = ", ".join(task.get("acceptance_checks", [])) or "none"
            lines.append(
                f"- `{task['id']}` {task['title']} | priority={task['priority']} size={task['size']} risk={task['risk']} deps={dep_text} checks={checks}"
            )

        lines.extend(["", "### Open Questions", ""])
        lines.extend(self._markdown_list(open_questions))
        lines.append("")
        return "\n".join(lines)

    def _extract_sections(self, text: str) -> dict[str, list[str]]:
        sections: dict[str, list[str]] = {}
        current = "__root__"
        sections[current] = []

        for raw_line in text.splitlines():
            heading = re.match(r"^#{1,6}\s+(.*)$", raw_line.strip())
            if heading:
                current = heading.group(1).strip().lower()
                sections.setdefault(current, [])
                continue
            sections.setdefault(current, []).append(raw_line)
        return sections

    def _items_from_sections(self, sections: dict[str, list[str]], markers: list[str]) -> list[str]:
        collected: list[str] = []
        for name, lines in sections.items():
            if not any(marker in name for marker in markers):
                continue
            collected.extend(self._extract_bullets_or_lines(lines))
        return self._dedupe([item for item in collected if item])

    def _extract_bullets_or_lines(self, lines: list[str]) -> list[str]:
        bullets: list[str] = []
        fallback: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
            if bullet:
                bullets.append(bullet.group(1).strip())
                continue
            numbered = re.match(r"^[0-9]+\.\s+(.*)$", stripped)
            if numbered:
                bullets.append(numbered.group(1).strip())
                continue
            fallback.append(stripped)
        return bullets or fallback

    def _fallback_items(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[:3]

    def _find_ambiguities(self, text: str) -> list[str]:
        ambiguous_markers = ["tbd", "todo", "unclear", "maybe", "open question", "?"]
        found: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            if any(marker in lower for marker in ambiguous_markers):
                found.append(stripped)
        return self._dedupe(found)

    def _likely_areas(
        self,
        *,
        text: str,
        repo_root: Path,
        repo_frontmatter: dict[str, Any],
    ) -> list[str]:
        lower = text.lower()
        areas: list[str] = []

        keyword_map = {
            "api": ["api", "endpoint", "http", "route"],
            "ui": ["ui", "frontend", "component", "screen"],
            "data": ["db", "database", "migration", "schema", "query"],
            "tests": ["test", "testing", "coverage", "verify"],
            "infra": ["infra", "deployment", "docker", "k8s"],
        }
        for area, markers in keyword_map.items():
            if any(marker in lower for marker in markers):
                areas.append(area)

        top_dirs = self._top_level_dirs(repo_root)
        for directory in top_dirs:
            if directory.lower() in {"src", "app", "api", "web", "tests", "migrations"}:
                areas.append(directory.lower())

        stack = repo_frontmatter.get("stack", [])
        if isinstance(stack, list):
            for item in stack:
                areas.append(str(item).lower())

        if not areas:
            areas.append("general")
        return self._dedupe(areas)

    def _summarize_intent(
        self,
        *,
        spec_title: str,
        goals: list[str],
        constraints: list[str],
        acceptance: list[str],
        likely_areas: list[str],
        ambiguities: list[str],
    ) -> str:
        goal_text = goals[0] if goals else spec_title
        area_text = ", ".join(likely_areas[:3])
        constraints_count = len(constraints)
        acceptance_count = len(acceptance)
        ambiguity_count = len(ambiguities)
        return (
            f"{goal_text}. Target areas: {area_text}. "
            f"Constraints: {constraints_count}, acceptance criteria: {acceptance_count}, ambiguities: {ambiguity_count}."
        )

    def _classify_item(self, item: str) -> str:
        lower = item.lower()
        if any(marker in lower for marker in ["test", "verify", "coverage", "assert"]):
            return "tests"
        if any(marker in lower for marker in ["db", "database", "migration", "schema"]):
            return "data"
        if any(marker in lower for marker in ["ui", "frontend", "component", "screen"]):
            return "ui"
        if any(marker in lower for marker in ["api", "endpoint", "http", "route"]):
            return "api"
        return "implementation"

    def _task_priority(self, item: str, default_priority: str) -> str:
        lower = item.lower()
        if any(marker in lower for marker in ["critical", "must", "security", "urgent"]):
            return "high"
        if default_priority in {"high", "medium", "low"}:
            return default_priority
        return "medium"

    def _task_size(self, item: str) -> str:
        lower = item.lower()
        if any(marker in lower for marker in ["overhaul", "rewrite", "redesign"]):
            return "large"
        if any(marker in lower for marker in ["migration", "refactor", "multiple"]):
            return "medium"
        return "small"

    def _task_risk(self, item: str) -> str:
        lower = item.lower()
        if any(
            marker in lower
            for marker in [
                "auth",
                "billing",
                "secret",
                "deployment",
                "production",
                "migration",
                "infra",
            ]
        ):
            return "high"
        if any(marker in lower for marker in ["permission", "security", "data"]):
            return "medium"
        return "low"

    def _task_title(self, item: str, category: str) -> str:
        cleaned = item.strip().rstrip(".")
        cleaned = cleaned[:80] if len(cleaned) > 80 else cleaned
        if category == "tests" and not cleaned.lower().startswith("add test"):
            return f"Add tests for {cleaned[:60]}"
        return cleaned[:1].upper() + cleaned[1:] if cleaned else "Implement spec task"

    def _task_description(self, item: str, category: str, analysis: SpecAnalysis) -> str:
        return (
            f"Implement spec item: {item}\n\n"
            f"Category: {category}\n"
            f"Spec intent: {analysis.intent_summary}"
        )

    def _acceptance_checks_for_category(
        self,
        category: str,
        command_map: dict[str, str],
    ) -> list[str]:
        available = [check for check in ["test", "lint", "typecheck", "build"] if check in command_map]
        if not available:
            return ["test"]

        if category == "tests":
            if "test" in available:
                return ["test"]
            return [available[0]]

        preferred = [check for check in ["test", "lint", "typecheck"] if check in available]
        if preferred:
            return preferred
        return [available[0]]

    def _assign_dependencies(self, plans: list[TaskPlan]) -> None:
        implementation_indexes = [index for index, plan in enumerate(plans) if "tests" not in plan.labels]
        for index, plan in enumerate(plans):
            if "tests" not in plan.labels:
                continue
            deps = [item for item in implementation_indexes if item < index]
            plan.depends_on_indexes = deps

    def _top_level_dirs(self, repo_root: Path) -> list[str]:
        if not repo_root.exists() or not repo_root.is_dir():
            return []
        names: list[str] = []
        for child in repo_root.iterdir():
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            names.append(child.name)
        return sorted(names)

    def _markdown_list(self, items: list[str]) -> list[str]:
        if not items:
            return ["- none"]
        return [f"- {item}" for item in items]

    def _dedupe(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result
