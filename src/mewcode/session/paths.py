"""项目内会话、缓存与记忆目录。"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SESSION_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
GITIGNORE_ENTRIES = (
    ".mewcode/sessions/",
    ".mewcode/cache/",
    ".mewcode/memory/",
)


@dataclass(frozen=True)
class SessionPaths:
    root: Path
    session_id: str
    archive_path: Path
    cache_dir: Path


def new_session_id(now: datetime | None = None) -> str:
    timestamp = (datetime.now() if now is None else now).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(2)}"


def paths_for(root: Path, session_id: str) -> SessionPaths:
    project_root = root.resolve()
    mewcode_dir = project_root / ".mewcode"
    return SessionPaths(
        root=project_root,
        session_id=session_id,
        archive_path=mewcode_dir / "sessions" / f"{session_id}.jsonl",
        cache_dir=mewcode_dir / "cache" / session_id,
    )


def create_session(root: Path, now: datetime | None = None) -> SessionPaths:
    ensure_project_layout(root)
    paths = paths_for(root, new_session_id(now))
    paths.archive_path.parent.mkdir(parents=True, exist_ok=True)
    paths.archive_path.touch(exist_ok=True)
    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    return paths


def ensure_project_layout(root: Path) -> None:
    project_root = root.resolve()
    mewcode_dir = project_root / ".mewcode"
    for name in ("sessions", "cache", "memory"):
        (mewcode_dir / name).mkdir(parents=True, exist_ok=True)
    _ensure_gitignore(project_root / ".gitignore")


def _ensure_gitignore(path: Path) -> None:
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        newline = "\r\n" if "\r\n" in existing else "\n"
        lines = existing.splitlines()
        missing = [entry for entry in GITIGNORE_ENTRIES if entry not in lines]
        if not missing:
            return
        prefix = "" if not existing or existing.endswith(("\n", "\r")) else newline
        path.write_text(
            f"{existing}{prefix}{newline.join(missing)}{newline}", encoding="utf-8"
        )
    except OSError:
        # Git 忽略规则创建失败不影响会话功能。
        return


__all__ = [
    "GITIGNORE_ENTRIES",
    "SESSION_ID_RE",
    "SessionPaths",
    "create_session",
    "ensure_project_layout",
    "new_session_id",
    "paths_for",
]
