"""Deterministic repository detection and command mapping."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RepoProfile:
    """Detected repository profile."""

    language: str
    stack: list[str]
    package_manager: str
    commands: dict[str, str]
    details: dict[str, Any] = field(default_factory=dict)


def detect_repo_profile(repo_root: Path) -> RepoProfile:
    """Detect repository type with deterministic precedence."""
    root = repo_root.resolve()
    detectors = [
        _detect_node_profile,
        _detect_python_profile,
        _detect_go_profile,
        _detect_rust_profile,
    ]

    for detector in detectors:
        profile = detector(root)
        if profile is not None:
            return profile

    return RepoProfile(
        language="unknown",
        stack=["unknown"],
        package_manager="unknown",
        commands={},
        details={},
    )


def _detect_node_profile(repo_root: Path) -> RepoProfile | None:
    package_json = repo_root / "package.json"
    if not package_json.exists():
        return None

    package_data = _read_json(package_json)
    scripts = package_data.get("scripts", {}) if isinstance(package_data, dict) else {}
    if not isinstance(scripts, dict):
        scripts = {}

    package_manager = _detect_node_package_manager(repo_root)
    language = "typescript" if (repo_root / "tsconfig.json").exists() else "javascript"

    commands: dict[str, str] = {}
    for script in ["test", "lint", "typecheck", "build"]:
        if script in scripts:
            commands[script] = _node_script_command(package_manager, script)

    details = {
        "framework": _detect_js_framework(package_data),
        "scripts": sorted(scripts.keys()),
    }

    stack = ["node", language]
    if details["framework"]:
        stack.append(str(details["framework"]))

    return RepoProfile(
        language=language,
        stack=stack,
        package_manager=package_manager,
        commands=commands,
        details=details,
    )


def _detect_python_profile(repo_root: Path) -> RepoProfile | None:
    pyproject = repo_root / "pyproject.toml"
    requirements = repo_root / "requirements.txt"
    setup_py = repo_root / "setup.py"

    if not (pyproject.exists() or requirements.exists() or setup_py.exists()):
        return None

    package_manager = "pip"
    pyproject_data: dict[str, Any] = {}

    if pyproject.exists():
        pyproject_data = _read_toml(pyproject)
        tool = pyproject_data.get("tool", {})
        if isinstance(tool, dict) and "poetry" in tool:
            package_manager = "poetry"

    if (repo_root / "uv.lock").exists():
        package_manager = "uv"
    elif (repo_root / "Pipfile").exists():
        package_manager = "pipenv"

    commands = _python_commands_for_manager(package_manager)

    return RepoProfile(
        language="python",
        stack=["python"],
        package_manager=package_manager,
        commands=commands,
        details={"pyproject": bool(pyproject_data)},
    )


def _detect_go_profile(repo_root: Path) -> RepoProfile | None:
    if not (repo_root / "go.mod").exists():
        return None

    commands = {
        "test": "go test ./...",
        "lint": "go vet ./...",
        "build": "go build ./...",
    }

    return RepoProfile(
        language="go",
        stack=["go"],
        package_manager="go",
        commands=commands,
        details={},
    )


def _detect_rust_profile(repo_root: Path) -> RepoProfile | None:
    if not (repo_root / "Cargo.toml").exists():
        return None

    commands = {
        "test": "cargo test",
        "lint": "cargo clippy --all-targets --all-features -- -D warnings",
        "build": "cargo build",
    }

    return RepoProfile(
        language="rust",
        stack=["rust"],
        package_manager="cargo",
        commands=commands,
        details={},
    )


def _detect_node_package_manager(repo_root: Path) -> str:
    if (repo_root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (repo_root / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _node_script_command(package_manager: str, script: str) -> str:
    if package_manager == "npm":
        if script == "test":
            return "npm test"
        return f"npm run {script}"
    return f"{package_manager} {script}"


def _python_commands_for_manager(package_manager: str) -> dict[str, str]:
    if package_manager == "poetry":
        return {
            "test": "poetry run pytest -q",
            "lint": "poetry run ruff check .",
            "typecheck": "poetry run mypy .",
            "build": "poetry build",
        }
    if package_manager == "uv":
        return {
            "test": "uv run pytest -q",
            "lint": "uv run ruff check .",
            "typecheck": "uv run mypy .",
            "build": "python -m build",
        }
    if package_manager == "pipenv":
        return {
            "test": "pipenv run pytest -q",
            "lint": "pipenv run ruff check .",
            "typecheck": "pipenv run mypy .",
            "build": "python -m build",
        }
    return {
        "test": "pytest -q",
        "lint": "ruff check .",
        "typecheck": "mypy .",
        "build": "python -m build",
    }


def _detect_js_framework(package_data: dict[str, Any]) -> str | None:
    deps: dict[str, Any] = {}
    for key in ["dependencies", "devDependencies"]:
        value = package_data.get(key, {})
        if isinstance(value, dict):
            deps.update(value)
    for marker in ["next", "react", "vue", "svelte", "astro"]:
        if marker in deps:
            return marker
    return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
