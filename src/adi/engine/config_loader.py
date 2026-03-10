"""Load and merge ADI configuration."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from adi.config.defaults import (
    ADI_CONFIG_NAME,
    MODELS_CONFIG_NAME,
    POLICIES_CONFIG_NAME,
    REPOS_CONFIG_NAME,
    default_config_bundle,
    get_adi_home,
)
from .yaml_utils import dump_yaml, load_yaml


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge dictionaries, returning a new object."""
    merged = deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


class ConfigLoader:
    """Manage ADI config files in ~/.adi/config."""

    def __init__(self, adi_home: Path | None = None) -> None:
        self.adi_home = (adi_home or get_adi_home()).resolve()

    @property
    def config_dir(self) -> Path:
        return self.adi_home / "config"

    @property
    def repos_dir(self) -> Path:
        return self.adi_home / "repos"

    @property
    def runs_dir(self) -> Path:
        return self.adi_home / "runs"

    @property
    def logs_dir(self) -> Path:
        return self.adi_home / "logs"

    @property
    def cache_dir(self) -> Path:
        return self.adi_home / "cache"

    @property
    def templates_dir(self) -> Path:
        return self.adi_home / "templates"

    def ensure_initialized(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.repos_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)

        defaults = default_config_bundle()
        for filename, payload in defaults.items():
            path = self.config_dir / filename
            if not path.exists():
                self._write_yaml(path, payload)

    def load_effective_config(self, repo_id: str | None = None) -> dict[str, Any]:
        self.ensure_initialized()
        defaults = default_config_bundle()

        merged = {
            name: deep_merge(payload, self._read_yaml(self.config_dir / name))
            for name, payload in defaults.items()
        }

        if repo_id:
            repo_override_path = self.repos_dir / repo_id / "state" / "repo-config.yaml"
            if repo_override_path.exists():
                merged[ADI_CONFIG_NAME] = deep_merge(
                    merged[ADI_CONFIG_NAME],
                    self._read_yaml(repo_override_path),
                )

        return {
            "adi": merged[ADI_CONFIG_NAME],
            "policies": merged[POLICIES_CONFIG_NAME],
            "models": merged[MODELS_CONFIG_NAME],
            "repos": merged[REPOS_CONFIG_NAME],
        }

    def load_repos_registry(self) -> list[dict[str, Any]]:
        self.ensure_initialized()
        payload = self._read_yaml(self.config_dir / REPOS_CONFIG_NAME)
        repos = payload.get("repos", [])
        if not isinstance(repos, list):
            raise ValueError("repos.yaml must contain a list at key 'repos'")
        return repos

    def save_repos_registry(self, repos: list[dict[str, Any]]) -> None:
        self.ensure_initialized()
        self._write_yaml(self.config_dir / REPOS_CONFIG_NAME, {"repos": repos})

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        data = load_yaml(path.read_text(encoding="utf-8"))
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"Config file must contain mapping: {path}")
        return data

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_yaml(data), encoding="utf-8")
