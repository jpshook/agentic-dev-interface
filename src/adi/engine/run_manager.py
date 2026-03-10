"""Run directory manager and run artifact recording."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .yaml_utils import dump_yaml


@dataclass(slots=True)
class RunContext:
    """Execution run context."""

    id: str
    dir: Path
    created_at: str


class RunManager:
    """Create deterministic run ids and write durable run artifacts."""

    def __init__(self, runs_root: Path) -> None:
        self.runs_root = runs_root.resolve()

    def start_run(self, repo_id: str, task_id: str, mode: str = "run") -> RunContext:
        self.runs_root.mkdir(parents=True, exist_ok=True)
        run_id = self._new_run_id(repo_id=repo_id, task_id=task_id, mode=mode)
        run_dir = self.runs_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        for subdir in ["prompts", "agent", "verification", "outputs"]:
            (run_dir / subdir).mkdir(parents=True, exist_ok=True)

        return RunContext(id=run_id, dir=run_dir, created_at=self._utc_now())

    def write_metadata(self, run: RunContext, metadata: dict[str, Any]) -> Path:
        path = run.dir / "metadata.yaml"
        path.write_text(dump_yaml(metadata), encoding="utf-8")
        return path

    def write_prompt(self, run: RunContext, role: str, attempt: int, prompt: str) -> Path:
        path = run.dir / "prompts" / f"attempt-{attempt:02d}-{role}.md"
        path.write_text(prompt, encoding="utf-8")
        return path

    def write_agent_result(
        self,
        run: RunContext,
        role: str,
        attempt: int,
        payload: dict[str, Any],
    ) -> Path:
        path = run.dir / "agent" / f"attempt-{attempt:02d}-{role}.yaml"
        path.write_text(dump_yaml(payload), encoding="utf-8")
        return path

    def write_verification_results(
        self,
        run: RunContext,
        verification_results: list[dict[str, object]],
        attempt: int | None = None,
    ) -> Path:
        if attempt is None:
            path = run.dir / "verification.yaml"
        else:
            path = run.dir / "verification" / f"attempt-{attempt:02d}.yaml"
        payload = {
            "results": verification_results,
            "all_passed": all(item.get("returncode") == 0 for item in verification_results),
        }
        path.write_text(dump_yaml(payload), encoding="utf-8")
        return path

    def write_command_outputs(
        self,
        run: RunContext,
        verification_results: list[dict[str, object]],
        attempt: int | None = None,
    ) -> Path:
        outputs_dir = run.dir / "outputs"
        if attempt is not None:
            outputs_dir = outputs_dir / f"attempt-{attempt:02d}"
        outputs_dir.mkdir(parents=True, exist_ok=True)

        for item in verification_results:
            check_name = str(item.get("check", "check"))
            safe_check = check_name.replace("/", "-")
            stdout_text = str(item.get("stdout", ""))
            stderr_text = str(item.get("stderr", ""))
            (outputs_dir / f"{safe_check}.stdout.log").write_text(stdout_text, encoding="utf-8")
            (outputs_dir / f"{safe_check}.stderr.log").write_text(stderr_text, encoding="utf-8")
        return outputs_dir

    def write_diff_summary(self, run: RunContext, diff_text: str) -> Path:
        path = run.dir / "changes.diff"
        path.write_text(diff_text, encoding="utf-8")
        return path

    def write_summary(self, run: RunContext, summary_markdown: str) -> Path:
        path = run.dir / "summary.md"
        path.write_text(summary_markdown, encoding="utf-8")
        return path

    def _new_run_id(self, repo_id: str, task_id: str, mode: str) -> str:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        suffix = secrets.token_hex(3)
        return f"{ts}-{mode}-{repo_id}-{task_id}-{suffix}"

    def _utc_now(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()
