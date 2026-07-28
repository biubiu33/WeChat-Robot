"""Agent-local cached results for successful file reads."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from mewcode.tool import Result


@dataclass(frozen=True)
class CachedRead:
    modified_ns: int
    size: int
    result: Result


class FileReadCache:
    """Keep read results private to one child runtime and verify freshness."""

    def __init__(self) -> None:
        self._entries: dict[Path, CachedRead] = {}

    async def get(self, path: Path) -> Result | None:
        normalized = _normalize(path)
        entry = self._entries.get(normalized)
        if entry is None:
            return None
        try:
            modified_ns, size = await asyncio.to_thread(_fingerprint, normalized)
        except OSError:
            self._entries.pop(normalized, None)
            return None
        if entry.modified_ns != modified_ns or entry.size != size:
            self._entries.pop(normalized, None)
            return None
        return entry.result

    def put(self, path: Path, result: Result) -> None:
        if result.is_error:
            return
        normalized = _normalize(path)
        try:
            modified_ns, size = _fingerprint(normalized)
        except OSError:
            return
        self._entries[normalized] = CachedRead(modified_ns, size, result)

    def invalidate(self, path: Path) -> None:
        self._entries.pop(_normalize(path), None)


def _normalize(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _fingerprint(path: Path) -> tuple[int, int]:
    status = path.stat()
    return status.st_mtime_ns, status.st_size


__all__ = ["CachedRead", "FileReadCache"]
