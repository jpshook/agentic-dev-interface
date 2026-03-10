"""Backlog task scheduler."""

from __future__ import annotations

from datetime import datetime
from typing import Any


_PRIORITY_RANK = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}

_SIZE_RANK = {
    "small": 0,
    "medium": 1,
    "large": 2,
}


class Scheduler:
    """Determine eligibility and ranking for backlog execution."""

    def eligible(
        self,
        tasks: list[dict[str, Any]],
        *,
        running_task_ids: set[str],
        policy_actions: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Return tasks that are ready for execution."""
        state_by_id = {
            str(task.get("id", "")): str(task.get("status", ""))
            for task in tasks
        }

        eligible: list[dict[str, Any]] = []
        for task in tasks:
            task_id = str(task.get("id", ""))
            if not task_id:
                continue
            if task_id in running_task_ids:
                continue
            if str(task.get("status", "")) != "approved":
                continue
            if not self._dependencies_satisfied(task, state_by_id):
                continue
            if policy_actions.get(task_id) != "auto_execute":
                continue
            eligible.append(task)
        return eligible

    def rank(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Rank tasks with deterministic heuristic ordering."""
        return sorted(tasks, key=self._sort_key)

    def select(self, tasks: list[dict[str, Any]], capacity: int) -> list[dict[str, Any]]:
        """Select top tasks up to available scheduler capacity."""
        if capacity <= 0:
            return []
        ranked = self.rank(tasks)
        return ranked[:capacity]

    def _dependencies_satisfied(
        self,
        task: dict[str, Any],
        state_by_id: dict[str, str],
    ) -> bool:
        depends_on = task.get("depends_on", [])
        if not isinstance(depends_on, list):
            return False
        for dep in depends_on:
            if state_by_id.get(str(dep), "") != "completed":
                return False
        return True

    def _sort_key(self, task: dict[str, Any]) -> tuple[int, int, int, float, str]:
        priority = str(task.get("priority", "medium")).lower()
        size = str(task.get("size", "medium")).lower()
        created_at = str(task.get("created_at", ""))
        task_id = str(task.get("id", ""))

        priority_rank = _PRIORITY_RANK.get(priority, 99)
        size_rank = _SIZE_RANK.get(size, 99)
        dependency_count = len(task.get("depends_on", []) or [])

        created_epoch = self._created_epoch(created_at)
        return (priority_rank, size_rank, dependency_count, created_epoch, task_id)

    def _created_epoch(self, created_at: str) -> float:
        if not created_at:
            return float("inf")
        normalized = created_at.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return float("inf")
