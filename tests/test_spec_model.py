import pytest

from adi.models.spec import assert_spec_transition, can_transition_spec, validate_spec_frontmatter


def _base_frontmatter() -> dict[str, object]:
    return {
        "id": "SP-001",
        "title": "Spec title",
        "repo_id": "demo-repo",
        "status": "draft",
        "priority": "medium",
        "created_at": "2026-03-10T00:00:00+00:00",
        "updated_at": "2026-03-10T00:00:00+00:00",
        "execution_mode": "manual",
    }


def test_spec_transition_rules() -> None:
    assert can_transition_spec("draft", "analyzed") is True
    assert can_transition_spec("draft", "approved") is False

    assert_spec_transition("decomposed", "approved")
    with pytest.raises(ValueError):
        assert_spec_transition("draft", "completed")


def test_spec_schema_validation() -> None:
    frontmatter = _base_frontmatter()
    validate_spec_frontmatter(frontmatter)

    missing = dict(frontmatter)
    missing.pop("title")
    with pytest.raises(ValueError, match="Missing required spec fields"):
        validate_spec_frontmatter(missing)

    bad_status = dict(frontmatter)
    bad_status["status"] = "proposed"
    with pytest.raises(ValueError, match="Invalid spec status"):
        validate_spec_frontmatter(bad_status)

    bad_mode = dict(frontmatter)
    bad_mode["execution_mode"] = "task"
    with pytest.raises(ValueError, match="Invalid spec execution_mode"):
        validate_spec_frontmatter(bad_mode)
