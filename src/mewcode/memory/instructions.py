"""三层项目指令的受限加载与 include 展开。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


INCLUDE_RE = re.compile(r"^@include <([^<>\r\n]+)>\s*$")
MAX_INCLUDE_DEPTH = 5


@dataclass(frozen=True)
class InstructionBundle:
    content: str
    warnings: tuple[str, ...] = ()


class InstructionLoader:
    def __init__(self, root: Path, home: Path | None = None) -> None:
        self._root = root.resolve()
        self._home_mewcode = (Path.home() if home is None else home) / ".mewcode"
        self._cached: InstructionBundle | None = None

    def load_once(self) -> InstructionBundle:
        if self._cached is not None:
            return self._cached
        warnings: list[str] = []
        sources = (
            (self._root / "MEWCODE.md", self._root),
            (self._root / ".mewcode" / "MEWCODE.md", self._root),
            (self._home_mewcode / "MEWCODE.md", self._home_mewcode),
        )
        contents = [
            self._expand(path, boundary, 1, set(), warnings)
            for path, boundary in sources
        ]
        self._cached = InstructionBundle(
            "\n\n".join(content for content in contents if content.strip()),
            tuple(warnings),
        )
        return self._cached

    def _expand(
        self,
        path: Path,
        boundary: Path,
        depth: int,
        visited: set[Path],
        warnings: list[str],
    ) -> str:
        try:
            resolved_boundary = boundary.resolve()
            resolved_path = path.resolve()
        except OSError:
            warnings.append(f"无法解析指令文件: {path}")
            return ""
        if not _within(resolved_path, resolved_boundary):
            warnings.append(f"include 路径超出允许范围，已跳过: {path}")
            return ""
        if depth > MAX_INCLUDE_DEPTH:
            warnings.append(f"include 超过最大嵌套深度，已跳过: {path}")
            return ""
        if resolved_path in visited:
            warnings.append(f"include 检测到环路，已跳过: {path}")
            return ""
        try:
            raw = resolved_path.read_bytes()
        except FileNotFoundError:
            return ""
        except OSError:
            warnings.append(f"无法读取指令文件: {path}")
            return ""
        if b"\0" in raw[:512]:
            warnings.append(f"include 引用了二进制文件，已跳过: {path}")
            return ""
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            warnings.append(f"include 引用了非 UTF-8 文件，已跳过: {path}")
            return ""

        visited.add(resolved_path)
        parts: list[str] = []
        for line in text.splitlines(keepends=True):
            match = INCLUDE_RE.fullmatch(line.rstrip("\r\n"))
            if match is None:
                parts.append(line)
                continue
            target = match.group(1).strip()
            if not target:
                parts.append(line)
                continue
            parts.append(
                self._expand(
                    resolved_path.parent / target,
                    resolved_boundary,
                    depth + 1,
                    visited,
                    warnings,
                )
            )
        return "".join(parts)


def _within(path: Path, boundary: Path) -> bool:
    try:
        path.relative_to(boundary)
        return True
    except ValueError:
        return False


__all__ = ["InstructionBundle", "InstructionLoader", "MAX_INCLUDE_DEPTH"]
