"""Repository onboarding and exploration services."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from adi.engine.artifact_store import ArtifactDocument, ArtifactStore
from adi.engine.config_loader import ConfigLoader
from adi.engine.repo_explorer import RepoProfile, detect_repo_profile
from adi.engine.yaml_utils import load_yaml
from adi.models.repo import RepoArtifact
from adi.services.spec_service import SpecService
from adi.services.task_service import TaskService


@dataclass(slots=True)
class DoctorCheck:
    name: str
    ok: bool
    details: str


class RepoService:
    """Service layer for repo init/explore/info/doctor."""

    def __init__(
        self,
        config_loader: ConfigLoader | None = None,
        artifact_store: ArtifactStore | None = None,
        task_service: TaskService | None = None,
        spec_service: SpecService | None = None,
    ) -> None:
        self.config_loader = config_loader or ConfigLoader()
        self.artifact_store = artifact_store or ArtifactStore()
        self.task_service = task_service or TaskService(config_loader=self.config_loader)
        self.spec_service = spec_service or SpecService(
            config_loader=self.config_loader,
            task_service=self.task_service,
        )

    def init_repo(self, path: Path) -> dict[str, Any]:
        repo_root = path.expanduser().resolve()
        if not repo_root.exists() or not repo_root.is_dir():
            raise ValueError(f"Repo path does not exist: {repo_root}")
        if not self._is_git_repo(repo_root):
            raise ValueError(f"Path is not a git repository: {repo_root}")

        self.config_loader.ensure_initialized()
        repos = self.config_loader.load_repos_registry()

        existing = self._find_repo_by_root(repos, repo_root)
        if existing is not None:
            return existing

        repo_name = repo_root.name
        repo_id = self._unique_repo_id(repos, repo_name)
        default_branch = self._detect_default_branch(repo_root)

        repo_state_dir = self.config_loader.repos_dir / repo_id
        for child in ["specs", "tasks", "backlog", "explore", "state"]:
            (repo_state_dir / child).mkdir(parents=True, exist_ok=True)

        repo_md_path = repo_state_dir / "repo.md"
        frontmatter = {
            "id": repo_id,
            "name": repo_name,
            "root": str(repo_root),
            "default_branch": default_branch,
            "status": "active",
            "commands": {},
        }
        body = (
            f"# Repository {repo_name}\n\n"
            f"Initialized by ADI on {self._utc_now()}.\n\n"
            "Run `adi repo explore --repo <repo>` to detect stack and commands.\n"
        )
        self.artifact_store.write(
            repo_md_path,
            ArtifactDocument(frontmatter=frontmatter, body=body),
            validator=RepoArtifact.from_frontmatter,
        )

        entry = {
            "id": repo_id,
            "name": repo_name,
            "root": str(repo_root),
            "default_branch": default_branch,
            "status": "active",
        }
        repos.append(entry)
        repos.sort(key=lambda item: str(item.get("id", "")))
        self.config_loader.save_repos_registry(repos)
        return entry

    def explore_repo(self, repo_ref: str) -> dict[str, Any]:
        entry = self._resolve_repo(repo_ref)
        repo_id = str(entry["id"])
        repo_root = Path(str(entry["root"])).resolve()

        if not repo_root.exists():
            raise ValueError(f"Repo path does not exist: {repo_root}")

        profile = detect_repo_profile(repo_root)
        repo_md_path = self.config_loader.repos_dir / repo_id / "repo.md"

        summary_body = self._render_repo_summary(entry, profile)
        updated = self.artifact_store.update(
            repo_md_path,
            frontmatter_updates={
                "language": profile.language,
                "stack": profile.stack,
                "package_manager": profile.package_manager,
                "commands": profile.commands,
                "last_explored_at": self._utc_now(),
            },
            body=summary_body,
            validator=RepoArtifact.from_frontmatter,
        )

        self._write_explore_snapshot(repo_id, profile)
        return {
            "repo": entry,
            "profile": {
                "language": profile.language,
                "stack": profile.stack,
                "package_manager": profile.package_manager,
                "commands": profile.commands,
                "details": profile.details,
            },
            "artifact": {
                "frontmatter": updated.frontmatter,
                "body": updated.body,
            },
        }

    def repo_info(self, repo_ref: str) -> dict[str, Any]:
        entry = self._resolve_repo(repo_ref)
        repo_id = str(entry["id"])
        repo_md_path = self.config_loader.repos_dir / repo_id / "repo.md"
        document = self.artifact_store.read(repo_md_path)
        return {
            "repo": entry,
            "artifact": {
                "frontmatter": document.frontmatter,
                "body": document.body,
            },
        }

    def repo_doctor(self, repo_ref: str) -> dict[str, Any]:
        entry = self._resolve_repo(repo_ref)
        repo_id = str(entry["id"])
        repo_root = Path(str(entry["root"])).resolve()
        repo_state_dir = self.config_loader.repos_dir / repo_id
        repo_md_path = repo_state_dir / "repo.md"

        checks: list[DoctorCheck] = []
        checks.append(
            DoctorCheck(
                name="repo_path_exists",
                ok=repo_root.exists() and repo_root.is_dir(),
                details=str(repo_root),
            )
        )
        checks.append(
            DoctorCheck(
                name="git_repository",
                ok=self._is_git_repo(repo_root),
                details="git rev-parse",
            )
        )

        config_files = [
            "adi.yaml",
            "policies.yaml",
            "models.yaml",
            "repos.yaml",
        ]
        for filename in config_files:
            path = self.config_loader.config_dir / filename
            checks.append(
                DoctorCheck(
                    name=f"config_{filename}",
                    ok=path.exists(),
                    details=str(path),
                )
            )

        checks.append(
            DoctorCheck(
                name="repo_state_dir",
                ok=repo_state_dir.exists(),
                details=str(repo_state_dir),
            )
        )
        checks.append(
            DoctorCheck(
                name="repo_md",
                ok=repo_md_path.exists(),
                details=str(repo_md_path),
            )
        )

        healthy = all(check.ok for check in checks)
        return {
            "repo": entry,
            "healthy": healthy,
            "checks": [asdict(check) for check in checks],
        }

    def delete_repo(self, repo_ref: str) -> dict[str, Any]:
        entry = self._resolve_repo(repo_ref)
        repo_id = str(entry["id"])
        repo_state_dir = self.config_loader.repos_dir / repo_id

        deleted_specs: list[str] = []
        specs_dir = repo_state_dir / "specs"
        if specs_dir.exists():
            for path in sorted(specs_dir.glob("*.md")):
                document = self.artifact_store.read(path)
                spec_id = str(document.frontmatter.get("id", "")).strip()
                if not spec_id:
                    continue
                self.spec_service.delete_spec(spec_id)
                deleted_specs.append(spec_id)

        deleted_tasks: list[str] = []
        tasks_dir = repo_state_dir / "tasks"
        if tasks_dir.exists():
            for path in sorted(tasks_dir.glob("*.md")):
                document = self.artifact_store.read(path)
                task_id = str(document.frontmatter.get("id", "")).strip()
                if not task_id:
                    continue
                self.task_service.delete_task(task_id)
                deleted_tasks.append(task_id)

        deleted_run_dirs = self._delete_repo_runs(repo_id)
        self._delete_repo_worktrees(repo_id)

        shutil.rmtree(repo_state_dir, ignore_errors=True)

        repos = [repo for repo in self.config_loader.load_repos_registry() if str(repo.get("id", "")) != repo_id]
        self.config_loader.save_repos_registry(repos)

        return {
            "repo": entry,
            "deleted": True,
            "deleted_spec_ids": deleted_specs,
            "deleted_task_ids": deleted_tasks,
            "deleted_run_dirs": deleted_run_dirs,
            "deleted_repo_state_dir": str(repo_state_dir),
        }

    def _resolve_repo(self, repo_ref: str) -> dict[str, Any]:
        repos = self.config_loader.load_repos_registry()
        for repo in repos:
            if repo_ref in {repo.get("id"), repo.get("name")}:
                return repo
        raise ValueError(f"Unknown repo: {repo_ref}")

    def _find_repo_by_root(
        self,
        repos: list[dict[str, Any]],
        root: Path,
    ) -> dict[str, Any] | None:
        root_str = str(root)
        for repo in repos:
            if repo.get("root") == root_str:
                return repo
        return None

    def _unique_repo_id(self, repos: list[dict[str, Any]], name: str) -> str:
        base = self._slugify(name)
        candidate = base
        suffix = 2
        existing_ids = {str(repo.get("id", "")) for repo in repos}
        while candidate in existing_ids:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
        return slug or "repo"

    def _utc_now(self) -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()

    def _is_git_repo(self, path: Path) -> bool:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"

    def _detect_default_branch(self, path: Path) -> str:
        remote_head = subprocess.run(
            ["git", "-C", str(path), "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if remote_head.returncode == 0 and remote_head.stdout.strip():
            short = remote_head.stdout.strip()
            if "/" in short:
                return short.split("/", 1)[1]
            return short

        current = subprocess.run(
            ["git", "-C", str(path), "branch", "--show-current"],
            check=False,
            capture_output=True,
            text=True,
        )
        if current.returncode == 0 and current.stdout.strip():
            return current.stdout.strip()

        return "main"

    def _write_explore_snapshot(self, repo_id: str, profile: RepoProfile) -> Path:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = self.config_loader.repos_dir / repo_id / "explore" / f"{ts}.md"
        frontmatter = {
            "repo_id": repo_id,
            "generated_at": self._utc_now(),
            "language": profile.language,
            "package_manager": profile.package_manager,
        }
        body_lines = [
            "# Repo Explore Snapshot",
            "",
            f"- Language: `{profile.language}`",
            f"- Stack: `{', '.join(profile.stack)}`",
            f"- Package manager: `{profile.package_manager}`",
            "",
            "## Commands",
            "",
        ]
        if profile.commands:
            for check, command in sorted(profile.commands.items()):
                body_lines.append(f"- `{check}`: `{command}`")
        else:
            body_lines.append("- No deterministic commands detected")

        self.artifact_store.write(
            path,
            ArtifactDocument(frontmatter=frontmatter, body="\n".join(body_lines) + "\n"),
        )
        return path

    def _delete_repo_runs(self, repo_id: str) -> list[str]:
        deleted: list[str] = []
        if not self.config_loader.runs_dir.exists():
            return deleted
        for run_dir in self.config_loader.runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            metadata_path = run_dir / "metadata.yaml"
            if not metadata_path.exists():
                continue
            payload = load_yaml(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue
            if str(payload.get("repo_id", "")) != repo_id:
                continue
            shutil.rmtree(run_dir, ignore_errors=True)
            deleted.append(str(run_dir))
        return deleted

    def _delete_repo_worktrees(self, repo_id: str) -> None:
        effective = self.config_loader.load_effective_config(repo_id=repo_id)
        worktree_root = Path(str(effective["adi"]["execution"]["worktree_root"])).expanduser()
        shutil.rmtree(worktree_root / repo_id, ignore_errors=True)

    def _render_repo_summary(self, entry: dict[str, Any], profile: RepoProfile) -> str:
        lines = [
            f"# Repository {entry['name']}",
            "",
            f"Root: `{entry['root']}`",
            f"Language: `{profile.language}`",
            f"Stack: `{', '.join(profile.stack)}`",
            f"Package manager: `{profile.package_manager}`",
            f"Explored at: `{self._utc_now()}`",
            "",
            "## Verification Commands",
            "",
        ]
        if profile.commands:
            for check, command in sorted(profile.commands.items()):
                lines.append(f"- `{check}`: `{command}`")
        else:
            lines.append("- None detected")
        return "\n".join(lines) + "\n"
