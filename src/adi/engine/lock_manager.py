"""Simple file lock manager placeholder."""

from __future__ import annotations

from pathlib import Path


class LockManager:
    """Create and remove lock files in deterministic locations."""

    def __init__(self, lock_root: Path) -> None:
        self.lock_root = lock_root

    def lock_path(self, name: str) -> Path:
        return self.lock_root / f"{name}.lock"
