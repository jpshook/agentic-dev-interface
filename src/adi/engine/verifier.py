"""Verification command mapping and execution helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .shell_runner import ShellRunner


@dataclass(slots=True)
class VerificationResult:
    check: str
    command: str
    returncode: int
    stdout: str
    stderr: str


class Verifier:
    """Run named verification checks using mapped commands."""

    def __init__(self, shell_runner: ShellRunner | None = None) -> None:
        self.shell_runner = shell_runner or ShellRunner()

    def resolve_commands(
        self,
        acceptance_checks: list[str],
        repo_command_map: dict[str, str],
    ) -> list[tuple[str, str]]:
        """Resolve abstract checks to concrete repository commands."""
        commands: list[tuple[str, str]] = []
        missing: list[str] = []
        for check in acceptance_checks:
            command = repo_command_map.get(check)
            if not command:
                missing.append(check)
                continue
            commands.append((check, command))
        if missing:
            labels = ", ".join(sorted(missing))
            raise ValueError(f"Missing repository command mappings for checks: {labels}")
        return commands

    def run_checks(
        self,
        repo_root: Path,
        check_commands: list[tuple[str, str]],
        timeout_seconds: int = 1200,
    ) -> list[VerificationResult]:
        """Run checks in order and collect structured results."""
        results: list[VerificationResult] = []
        for check, command in check_commands:
            result = self.run_check(
                repo_root=repo_root,
                check=check,
                command=command,
                timeout_seconds=timeout_seconds,
            )
            results.append(result)
        return results

    def all_passed(self, results: list[VerificationResult]) -> bool:
        return all(item.returncode == 0 for item in results)

    def to_serializable(self, results: list[VerificationResult]) -> list[dict[str, object]]:
        return [asdict(result) for result in results]

    def run_check(
        self,
        repo_root: Path,
        check: str,
        command: str,
        timeout_seconds: int = 1200,
    ) -> VerificationResult:
        result = self.shell_runner.run(
            command=command,
            cwd=repo_root,
            timeout_seconds=timeout_seconds,
        )
        return VerificationResult(
            check=check,
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
