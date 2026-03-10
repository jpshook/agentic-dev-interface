from pathlib import Path

from adi.engine.spec_planner import SpecPlanner


def test_spec_planner_analysis_extracts_key_sections(tmp_path: Path) -> None:
    planner = SpecPlanner()
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)

    body = """# Feature Spec

## Goals
- Add endpoint validation

## Constraints
- No schema changes

## Acceptance Criteria
- Add request validation tests
- Keep lint clean

## Open Questions
- TBD: edge-case behavior?
"""

    analysis = planner.analyze(
        spec_title="Feature Spec",
        spec_body=body,
        repo_root=repo,
        repo_frontmatter={"stack": ["python"]},
    )

    assert analysis.goals == ["Add endpoint validation"]
    assert "No schema changes" in analysis.constraints
    assert len(analysis.acceptance_criteria) == 2
    assert analysis.ambiguities
    assert "tests" in analysis.likely_areas


def test_spec_planner_decompose_generates_dependency_graph() -> None:
    planner = SpecPlanner()
    analysis = planner.analyze(
        spec_title="Feature",
        spec_body="""## Acceptance Criteria
- Implement API handler
- Add tests for API handler
""",
        repo_root=Path("."),
        repo_frontmatter={"stack": ["python"]},
    )

    plans = planner.decompose(
        analysis=analysis,
        repo_frontmatter={"commands": {"test": "pytest -q", "lint": "ruff check ."}},
        default_priority="medium",
    )

    assert len(plans) >= 2
    assert plans[0].acceptance_checks
    test_plan = plans[1]
    assert "tests" in test_plan.labels
    assert test_plan.depends_on_indexes == [0]
