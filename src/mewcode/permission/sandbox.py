from __future__ import annotations

from pathlib import Path


def resolve_root(root: str | Path) -> Path:
    path = Path(root).expanduser()
    return path.resolve(strict=True)


def resolve_target(root: Path, path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    return _resolve_with_ancestor(candidate)


def sandbox_ok(root: Path, path: str) -> bool:
    try:
        resolve_target(root, path).relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _resolve_with_ancestor(path: Path) -> Path:
    """解析链接；新文件则解析最近的已存在祖先。"""

    current = path
    suffix: list[str] = []
    while not current.exists() and not current.is_symlink():
        parent = current.parent
        if parent == current:
            return current.resolve(strict=False)
        suffix.append(current.name)
        current = parent

    resolved = current.resolve(strict=False)
    for part in reversed(suffix):
        resolved /= part
    return resolved
