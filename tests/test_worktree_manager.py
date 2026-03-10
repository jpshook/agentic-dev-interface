import subprocess
from pathlib import Path

from adi.engine.worktree_manager import WorktreeManager


def _init_git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init"], check=True, capture_output=True)
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], check=True, capture_output=True)
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


def test_worktree_manager_creates_task_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    branch = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    manager = WorktreeManager(tmp_path / "worktrees")
    worktree_path, worktree_branch = manager.ensure_worktree(
        repo_root=repo,
        repo_id="demo-repo",
        task_id="TK-001",
        base_branch=branch,
    )

    assert worktree_path.exists()
    assert worktree_branch == "adi/TK-001"

    listed = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "adi/TK-001"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert "adi/TK-001" in listed

    second_path, _ = manager.ensure_worktree(
        repo_root=repo,
        repo_id="demo-repo",
        task_id="TK-001",
        base_branch=branch,
    )
    assert second_path == worktree_path
