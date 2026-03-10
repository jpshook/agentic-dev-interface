from pathlib import Path

import pytest

from adi.engine.verifier import Verifier


def test_verifier_resolve_commands_and_run(tmp_path: Path) -> None:
    verifier = Verifier()

    check_commands = verifier.resolve_commands(
        acceptance_checks=["test", "lint"],
        repo_command_map={
            "test": "echo ok",
            "lint": "echo lint",
        },
    )

    results = verifier.run_checks(tmp_path, check_commands)
    assert len(results) == 2
    assert verifier.all_passed(results) is True


def test_verifier_missing_command_mapping() -> None:
    verifier = Verifier()
    with pytest.raises(ValueError, match="Missing repository command mappings"):
        verifier.resolve_commands(
            acceptance_checks=["test", "typecheck"],
            repo_command_map={"test": "echo ok"},
        )


def test_verifier_failure_detection(tmp_path: Path) -> None:
    verifier = Verifier()
    results = verifier.run_checks(
        tmp_path,
        [
            ("test", "echo ok"),
            ("lint", "sh -c 'exit 1'"),
        ],
    )
    assert verifier.all_passed(results) is False
