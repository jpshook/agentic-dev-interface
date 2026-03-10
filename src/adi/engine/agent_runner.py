"""Model-agnostic agent runner with shell runtime for Phase 4."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from adi.engine.config_loader import ConfigLoader
from adi.engine.shell_runner import ShellRunner


@dataclass(slots=True)
class AgentResult:
    """Normalized agent execution result."""

    role: str
    runtime: str
    success: bool
    returncode: int
    command: str
    response: str
    stdout: str
    stderr: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentRunner:
    """Execute role prompts using configured runtime backends."""

    def __init__(
        self,
        config_loader: ConfigLoader | None = None,
        shell_runner: ShellRunner | None = None,
    ) -> None:
        self.config_loader = config_loader or ConfigLoader()
        self.shell_runner = shell_runner or ShellRunner()

    def run(
        self,
        *,
        role: str,
        repo_id: str,
        prompt: str,
        prompt_path: Path,
        worktree_path: Path,
        run_dir: Path,
        attempt: int,
    ) -> AgentResult:
        config = self._role_config(repo_id=repo_id, role=role)
        runtime = str(config.get("runtime", "stub"))

        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")

        if runtime == "stub":
            response = "Stub runtime executed. No changes applied."
            return AgentResult(
                role=role,
                runtime=runtime,
                success=True,
                returncode=0,
                command="",
                response=response,
                stdout=response,
                stderr="",
            )

        if runtime == "shell":
            command_template = str(config.get("command", "")).strip()
            if not command_template:
                raise ValueError(f"No shell command configured for role '{role}'")
            command = command_template.format(
                prompt_file=str(prompt_path),
                worktree_path=str(worktree_path),
                run_dir=str(run_dir),
                attempt=attempt,
                role=role,
            )
            timeout = int(config.get("timeout_seconds", 600))
            result = self.shell_runner.run(
                command=command,
                cwd=worktree_path,
                timeout_seconds=timeout,
            )
            response = result.stdout.strip() or result.stderr.strip()
            return AgentResult(
                role=role,
                runtime=runtime,
                success=result.returncode == 0,
                returncode=result.returncode,
                command=command,
                response=response,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        raise ValueError(f"Unsupported agent runtime '{runtime}' for role '{role}'")

    def _role_config(self, repo_id: str, role: str) -> dict[str, Any]:
        effective = self.config_loader.load_effective_config(repo_id=repo_id)
        models_root = effective.get("models", {})
        if not isinstance(models_root, dict):
            return {"runtime": "stub"}

        models_cfg = models_root.get("models", {})
        if not isinstance(models_cfg, dict):
            return {"runtime": "stub"}

        role_cfg = models_cfg.get(role, {"runtime": "stub"})
        if isinstance(role_cfg, str):
            return {"runtime": role_cfg}
        if isinstance(role_cfg, dict):
            return role_cfg
        return {"runtime": "stub"}
