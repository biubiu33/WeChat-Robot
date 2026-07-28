from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import (
    SKILL_NAME_RE,
    Skill,
    SkillDiagnostic,
    SkillMetadata,
    SkillMode,
    SkillParseError,
    SkillSource,
    skill_body,
)


@dataclass(frozen=True)
class _Location:
    source: SkillSource
    root: Path


class SkillCatalog:
    def __init__(
        self,
        project_root: Path,
        user_root: Path,
        builtin_root: Path,
        skills: dict[str, Skill],
        diagnostics: tuple[SkillDiagnostic, ...],
        snapshot: tuple[tuple[str, int, int], ...],
    ) -> None:
        self._project_root = project_root
        self._user_root = user_root
        self._builtin_root = builtin_root
        self._skills = skills
        self._diagnostics = diagnostics
        self._snapshot = snapshot

    @classmethod
    def load(
        cls,
        project_root: Path,
        user_root: Path | None = None,
        builtin_root: Path | None = None,
    ) -> SkillCatalog:
        project_skills = project_root.resolve() / ".mewcode" / "skills"
        user_skills = (
            Path.home() / ".mewcode" / "skills"
            if user_root is None
            else user_root.resolve()
        )
        builtins = (
            Path(__file__).with_name("builtin")
            if builtin_root is None
            else builtin_root.resolve()
        )
        locations = (
            _Location(SkillSource.BUILTIN, builtins),
            _Location(SkillSource.USER, user_skills),
            _Location(SkillSource.PROJECT, project_skills),
        )
        skills, diagnostics = _discover(locations)
        return cls(
            project_root.resolve(),
            user_skills,
            builtins,
            skills,
            tuple(diagnostics),
            _snapshot(locations),
        )

    def effective(self) -> tuple[Skill, ...]:
        return tuple(self._skills[name] for name in sorted(self._skills))

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name.strip().lower())

    def diagnostics(self) -> tuple[SkillDiagnostic, ...]:
        return self._diagnostics

    @property
    def user_root(self) -> Path:
        """Return the user-level installation directory for this catalog."""
        return self._user_root

    def has_changed(self) -> bool:
        return self._snapshot != _snapshot(self._locations())

    def reloaded(self) -> SkillCatalog:
        return self.load(self._project_root, self._user_root, self._builtin_root)

    def refresh_if_changed(self) -> bool:
        if not self.has_changed():
            return False
        updated = self.reloaded()
        self._skills = updated._skills
        self._diagnostics = updated._diagnostics
        self._snapshot = updated._snapshot
        return True

    def _locations(self) -> tuple[_Location, ...]:
        return (
            _Location(SkillSource.BUILTIN, self._builtin_root),
            _Location(SkillSource.USER, self._user_root),
            _Location(SkillSource.PROJECT, self._project_root / ".mewcode" / "skills"),
        )


def parse_skill(
    entry_path: Path,
    source: SkillSource,
    package_root: Path | None = None,
) -> Skill:
    try:
        content = entry_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillParseError(f"无法读取 Skill: {exc}") from exc
    raw = _parse_frontmatter(content)
    metadata = _parse_metadata(raw)
    skill_body(content)
    return Skill(metadata, source, entry_path, package_root or entry_path.parent)


def validate_allowed_tools(skills: Iterable[Skill], names: Iterable[str]) -> None:
    available = set(names)
    for skill in skills:
        missing = sorted(skill.metadata.allowed_tools - available)
        if missing:
            rendered = ", ".join(missing)
            raise SkillParseError(
                f"Skill {skill.metadata.name} 声明了不存在的工具: {rendered}"
            )


def _discover(
    locations: tuple[_Location, ...],
) -> tuple[dict[str, Skill], list[SkillDiagnostic]]:
    effective: dict[str, Skill] = {}
    diagnostics: list[SkillDiagnostic] = []
    for location in locations:
        source_skills: dict[str, Skill] = {}
        for entry, package_root in _entries(location.root):
            try:
                skill = parse_skill(entry, location.source, package_root)
            except SkillParseError as exc:
                diagnostics.append(SkillDiagnostic(entry, str(exc)))
                continue
            previous = source_skills.get(skill.metadata.name)
            if previous is not None:
                diagnostics.append(
                    SkillDiagnostic(
                        entry,
                        f"同一位置存在重复 Skill 名称: {skill.metadata.name}",
                    )
                )
                continue
            source_skills[skill.metadata.name] = skill
        effective.update(source_skills)
    return effective, diagnostics


def _entries(root: Path) -> list[tuple[Path, Path]]:
    try:
        children = sorted(root.iterdir(), key=lambda path: path.name.lower())
    except OSError:
        return []
    entries: list[tuple[Path, Path]] = []
    for item in children:
        if _is_file(item) and item.suffix.lower() == ".md":
            entries.append((item, item.parent))
        elif _is_dir(item):
            entry = item / "SKILL.md"
            if _is_file(entry):
                entries.append((entry, item))
    return entries


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _parse_frontmatter(content: str) -> dict[str, Any]:
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillParseError("Skill 必须以 YAML frontmatter 开始")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue
        raw = "".join(lines[1:index])
        try:
            import yaml

            value = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise SkillParseError(f"YAML frontmatter 格式错误: {exc}") from exc
        if not isinstance(value, dict):
            raise SkillParseError("YAML frontmatter 必须是对象")
        return value
    raise SkillParseError("Skill frontmatter 缺少结束标记")


def _parse_metadata(raw: dict[str, Any]) -> SkillMetadata:
    name = _required_string(raw, "name")
    if SKILL_NAME_RE.fullmatch(name) is None:
        raise SkillParseError("Skill 名称只能包含小写字母、数字和连字符")
    description = _required_string(raw, "description")
    if "\n" in description:
        raise SkillParseError("Skill 说明必须是一句话")
    allowed_raw = raw.get("allowed_tools")
    if not isinstance(allowed_raw, list) or any(
        not isinstance(name, str) or not name.strip() for name in allowed_raw
    ):
        raise SkillParseError("allowed_tools 必须是工具名称列表")
    allowed_tools = frozenset(name.strip() for name in allowed_raw)
    mode_raw = _required_string(raw, "mode")
    try:
        mode = SkillMode(mode_raw)
    except ValueError as exc:
        raise SkillParseError("mode 必须是 inline 或 fork") from exc
    fork_history = _required_string(raw, "fork_history")
    if fork_history != "none":
        raise SkillParseError("fork_history 当前只能是 none")
    model = raw.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise SkillParseError("model 必须是非空字符串或省略")
    return SkillMetadata(
        name=name,
        description=description,
        allowed_tools=allowed_tools,
        mode=mode,
        fork_history=fork_history,
        model=model.strip() if isinstance(model, str) else None,
    )


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillParseError(f"{key} 必须是非空字符串")
    return value.strip()


def _snapshot(locations: tuple[_Location, ...]) -> tuple[tuple[str, int, int], ...]:
    entries: list[tuple[str, int, int]] = []
    for location in locations:
        root = location.root
        if not root.exists():
            entries.append((f"{location.source}:missing", 0, 0))
            continue
        for path in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append(
                (
                    f"{location.source}:{path.relative_to(root)}",
                    stat.st_mtime_ns,
                    stat.st_size,
                )
            )
    return tuple(entries)


__all__ = ["SkillCatalog", "parse_skill", "validate_allowed_tools"]
