"""File lock manager with stale lock handling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(slots=True)
class LockHandle:
    """Active lock handle."""

    name: str
    path: Path


class LockManager:
    """Create and remove lock files in deterministic locations."""

    def __init__(self, lock_root: Path, stale_after_seconds: int = 7200) -> None:
        self.lock_root = lock_root
        self.stale_after_seconds = stale_after_seconds

    def lock_path(self, name: str) -> Path:
        return self.lock_root / f"{name}.lock"

    def acquire(self, name: str) -> LockHandle:
        path = self.lock_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists() and self._is_stale(path):
            path.unlink(missing_ok=True)

        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(f"Lock already held: {name}") from exc

        payload = f"pid={os.getpid()}\ncreated_at={datetime.now(UTC).isoformat()}\n"
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(payload)

        return LockHandle(name=name, path=path)

    def release(self, handle: LockHandle) -> None:
        handle.path.unlink(missing_ok=True)

    def _is_stale(self, path: Path) -> bool:
        age_seconds = datetime.now(UTC).timestamp() - path.stat().st_mtime
        return age_seconds > self.stale_after_seconds
