import os
import subprocess
from pathlib import Path

from adi.cli.main import main
from adi.engine.artifact_store import ArtifactDocument, ArtifactStore
from adi.engine.config_loader import ConfigLoader
from adi.engine.yaml_utils import dump_yaml, load_yaml


def _init_retry_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)

    src_dir = path / "src"
    tests_dir = path / "tests"
    src_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    (path / "pyproject.toml").write_text("[project]\nname='retry-demo'\n", encoding="utf-8")
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "value.py").write_text("VALUE = 'BROKEN'\n", encoding="utf-8")
    (tests_dir / "test_value.py").write_text(
        "from pathlib import Path\n\n\ndef test_value():\n    assert \"FIXED\" in Path(\"src/value.py\").read_text()\n",
        encoding="utf-8",
    )

    script = path / "agent_apply.sh"
    script.write_text(
        "#!/bin/sh\n"
        "attempt=\"$1\"\n"
        "if [ \"$attempt\" = \"1\" ]; then\n"
        "  echo 'attempt 1 noop'\n"
        "  exit 0\n"
        "fi\n"
        "python3 -c \"from pathlib import Path; p=Path('src/value.py'); p.write_text(p.read_text().replace('BROKEN', 'FIXED'))\"\n"
        "echo 'fixed on retry'\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o755)

    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "init",
        ],
        check=True,
        capture_output=True,
    )


def _write_task(adi_home: Path, repo_id: str, task_id: str) -> None:
    store = ArtifactStore()
    task_path = adi_home / "repos" / repo_id / "tasks" / f"{task_id}.md"
    store.write(
        task_path,
        ArtifactDocument(
            frontmatter={
                "id": task_id,
                "title": f"Task {task_id}",
                "repo_id": repo_id,
                "status": "approved",
                "priority": "medium",
                "size": "small",
                "risk": "low",
                "created_at": "2026-03-10T00:00:00+00:00",
                "updated_at": "2026-03-10T00:00:00+00:00",
                "depends_on": [],
                "acceptance_checks": ["test"],
            },
            body=f"# {task_id}\n\nFix failing test.\n",
        ),
    )


def test_task_run_retries_and_completes_with_agent_changes(tmp_path: Path, monkeypatch, capsys) -> None:
    adi_home = tmp_path / ".adi-home"
    monkeypatch.setenv("ADI_HOME", str(adi_home))

    repo_path = tmp_path / "RetryRepo"
    _init_retry_repo(repo_path)

    assert main(["repo", "init", "--path", str(repo_path)]) == 0
    repo_id = load_yaml(capsys.readouterr().out)["repo"]["id"]

    loader = ConfigLoader(adi_home=adi_home)
    loader.ensure_initialized()
    (loader.config_dir / "adi.yaml").write_text(
        dump_yaml(
            {
                "execution": {
                    "worktree_root": str(tmp_path / "worktrees"),
                    "default_timeout_seconds": 120,
                    "verification_fix_cycles": 2,
                    "total_task_attempts": 3,
                }
            }
        ),
        encoding="utf-8",
    )
    (loader.config_dir / "models.yaml").write_text(
        dump_yaml(
            {
                "models": {
                    "implementer": {
                        "runtime": "shell",
                        "command": "sh agent_apply.sh {attempt}",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert main(["repo", "explore", "--repo", repo_id]) == 0
    capsys.readouterr()

    _write_task(adi_home, repo_id, "TK-RETRY")

    assert main(["task", "run", "TK-RETRY"]) == 0
    run_payload = load_yaml(capsys.readouterr().out)

    assert run_payload["status"] == "completed"
    assert len(run_payload["attempts"]) == 2
    assert run_payload["attempts"][0]["verification_passed"] is False
    assert run_payload["attempts"][1]["verification_passed"] is True

    run_dir = Path(run_payload["run_dir"])
    assert (run_dir / "prompts" / "attempt-01-implementer.md").exists()
    assert (run_dir / "agent" / "attempt-01-implementer.yaml").exists()
    assert (run_dir / "verification" / "attempt-01.yaml").exists()
    assert (run_dir / "verification" / "attempt-02.yaml").exists()
    assert (run_dir / "summary.md").exists()

    assert main(["task", "show", "TK-RETRY"]) == 0
    show_payload = load_yaml(capsys.readouterr().out)
    assert show_payload["task"]["frontmatter"]["status"] == "completed"
