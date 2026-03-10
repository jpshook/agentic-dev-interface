import pytest

from adi.models.task import assert_task_transition, can_transition_task, validate_task_frontmatter


def _base_frontmatter() -> dict[str, object]:
    return {
        "id": "TK-001",
        "title": "Sample task",
        "repo_id": "demo-repo",
        "status": "proposed",
        "priority": "medium",
        "size": "small",
        "risk": "low",
        "created_at": "2026-03-10T00:00:00+00:00",
        "updated_at": "2026-03-10T00:00:00+00:00",
        "depends_on": [],
        "acceptance_checks": ["test"],
    }


def test_task_transition_rules() -> None:
    assert can_transition_task("approved", "in_progress") is True
    assert can_transition_task("approved", "completed") is False

    assert_task_transition("in_progress", "failed")
    with pytest.raises(ValueError):
        assert_task_transition("proposed", "completed")


def test_task_schema_validation() -> None:
    frontmatter = _base_frontmatter()
    validate_task_frontmatter(frontmatter)

    broken = dict(frontmatter)
    broken.pop("title")
    with pytest.raises(ValueError, match="Missing required task fields"):
        validate_task_frontmatter(broken)

    broken_status = dict(frontmatter)
    broken_status["status"] = "skipped"
    with pytest.raises(ValueError, match="Invalid task status"):
        validate_task_frontmatter(broken_status)

    broken_checks = dict(frontmatter)
    broken_checks["acceptance_checks"] = "test"
    with pytest.raises(ValueError, match="acceptance_checks"):
        validate_task_frontmatter(broken_checks)
