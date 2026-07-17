"""自动记忆笔记和索引的安全存储。"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


MemoryType = Literal["user", "feedback", "project", "reference"]
MemoryLevel = Literal["user", "project"]
_TYPE_LEVEL: dict[str, str] = {
    "user": "user",
    "feedback": "user",
    "project": "project",
    "reference": "project",
}
_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*\.md$")
MAX_INDEX_LINES = 200
MAX_INDEX_BYTES = 25 * 1024


@dataclass(frozen=True)
class NoteOperation:
    action: Literal["create", "update"]
    level: MemoryLevel
    type: MemoryType
    title: str
    filename: str
    content: str


class MemoryStore:
    def __init__(self, root: Path, home: Path | None = None) -> None:
        self._root = root.resolve()
        self._project_dir = self._root / ".mewcode" / "memory"
        self._user_dir = (Path.home() if home is None else home) / ".mewcode" / "memory"
        self._lock = asyncio.Lock()

    def prompt_index(self) -> str:
        return _truncate(
            "\n".join(
                filter(None, (self._read_index("project"), self._read_index("user")))
            )
        )

    def index_exceeds_limit(self) -> bool:
        return any(_exceeds(self._read_index(level)) for level in ("project", "user"))

    async def apply(
        self, operations: list[NoteOperation], indexes: dict[str, str] | None = None
    ) -> None:
        async with self._lock:
            for operation in operations:
                self._apply_one(operation)
            if indexes:
                for level, content in indexes.items():
                    if level in {"user", "project"}:
                        self._write_index(level, _truncate(content))

    def _apply_one(self, operation: NoteOperation) -> None:
        if _TYPE_LEVEL.get(operation.type) != operation.level:
            raise ValueError("记忆类型与存储层级不匹配")
        if not _FILENAME_RE.fullmatch(operation.filename):
            raise ValueError("记忆文件名不安全")
        directory = self._directory(operation.level)
        directory.mkdir(parents=True, exist_ok=True)
        target = (directory / operation.filename).resolve()
        if target.parent != directory.resolve():
            raise ValueError("记忆文件路径超出目录")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        created = now
        if target.exists() and operation.action == "update":
            created = (
                _frontmatter_value(target.read_text(encoding="utf-8"), "created") or now
            )
        target.write_text(
            "---\n"
            f"type: {operation.type}\n"
            f"title: {operation.title}\n"
            f"created: {created}\n"
            f"updated: {now}\n"
            "---\n"
            f"{operation.content.strip()}\n",
            encoding="utf-8",
        )
        self._replace_index_line(
            operation.level,
            operation.filename,
            operation.type,
            operation.title,
            operation.content,
        )

    def _replace_index_line(
        self, level: str, filename: str, note_type: str, title: str, content: str
    ) -> None:
        marker = f"<!-- {filename} -->"
        lines = [
            line for line in self._read_index(level).splitlines() if marker not in line
        ]
        description = " ".join(content.split())[:160]
        lines.append(f"- [{note_type}] {title} — {description} {marker}")
        self._write_index(level, "\n".join(lines) + "\n")

    def _read_index(self, level: str) -> str:
        try:
            return (self._directory(level) / "MEMORY.md").read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return ""

    def _write_index(self, level: str, content: str) -> None:
        directory = self._directory(level)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "MEMORY.md").write_text(content, encoding="utf-8")

    def _directory(self, level: str) -> Path:
        return self._project_dir if level == "project" else self._user_dir


def _frontmatter_value(text: str, key: str) -> str:
    prefix = f"{key}: "
    for line in text.splitlines()[1:8]:
        if line.startswith(prefix):
            return line[len(prefix) :]
    return ""


def _exceeds(content: str) -> bool:
    return (
        len(content.splitlines()) > MAX_INDEX_LINES
        or len(content.encode("utf-8")) > MAX_INDEX_BYTES
    )


def _truncate(content: str) -> str:
    encoded = content.encode("utf-8")
    if len(encoded) <= MAX_INDEX_BYTES:
        return content
    return (
        encoded[: MAX_INDEX_BYTES - 20].decode("utf-8", errors="ignore")
        + "\n(index truncated)\n"
    )


__all__ = ["MAX_INDEX_BYTES", "MAX_INDEX_LINES", "MemoryStore", "NoteOperation"]
