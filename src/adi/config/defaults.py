"""Built-in defaults and filesystem helpers."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

ADI_CONFIG_NAME = "adi.yaml"
POLICIES_CONFIG_NAME = "policies.yaml"
MODELS_CONFIG_NAME = "models.yaml"
REPOS_CONFIG_NAME = "repos.yaml"

DEFAULT_ADI_HOME = Path("~/.adi").expanduser()
DEFAULT_WORKTREE_ROOT = Path("~/agent-worktrees").expanduser()

DEFAULT_ADI_CONFIG: dict[str, Any] = {
    "artifact": {
        "templates_dir": "templates",
    },
    "execution": {
        "worktree_root": str(DEFAULT_WORKTREE_ROOT),
        "default_timeout_seconds": 1200,
    },
    "verification": {
        "default_checks": ["test", "lint", "typecheck", "build"],
    },
}

DEFAULT_POLICIES_CONFIG: dict[str, Any] = {
    "policy": {
        "default_action": "require_approval",
        "auto_execute": {
            "max_size": "small",
            "max_risk": "low",
        },
        "restricted_areas": [
            "auth",
            "billing",
            "migrations",
            "infra",
            "deployment",
            "secrets",
            "production",
        ],
    }
}

DEFAULT_MODELS_CONFIG: dict[str, Any] = {
    "models": {
        "implementer": "stub",
        "reviewer": "stub",
    }
}

DEFAULT_REPOS_CONFIG: dict[str, Any] = {"repos": []}


def get_adi_home() -> Path:
    """Return ADI home, honoring ADI_HOME override."""
    return Path(os.environ.get("ADI_HOME", str(DEFAULT_ADI_HOME))).expanduser().resolve()


def default_config_bundle() -> dict[str, dict[str, Any]]:
    """Return deep-copied config defaults keyed by filename."""
    return {
        ADI_CONFIG_NAME: deepcopy(DEFAULT_ADI_CONFIG),
        POLICIES_CONFIG_NAME: deepcopy(DEFAULT_POLICIES_CONFIG),
        MODELS_CONFIG_NAME: deepcopy(DEFAULT_MODELS_CONFIG),
        REPOS_CONFIG_NAME: deepcopy(DEFAULT_REPOS_CONFIG),
    }
