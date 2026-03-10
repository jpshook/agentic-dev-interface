"""Verification command mapping and execution helpers."""

from __future__ import annotations

from dataclasses import dataclass
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

    def run_check(self, repo_root: Path, check: str, command: str) -> VerificationResult:
        result = self.shell_runner.run(command=command, cwd=repo_root)
        return VerificationResult(
            check=check,
            command=command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
