"""Shell execution utility."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ShellResult:
    returncode: int
    stdout: str
    stderr: str


class ShellRunner:
    """Thin wrapper around subprocess for deterministic command execution."""

    def run(self, command: str, cwd: Path, timeout_seconds: int = 1200) -> ShellResult:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            shell=True,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return ShellResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
