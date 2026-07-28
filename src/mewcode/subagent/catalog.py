"""Markdown definition discovery for sub-agent roles."""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import (
    AgentDiagnostic,
    Definition,
    DefinitionError,
    DefinitionSource,
    NAME_RE,
    PermissionMode,
    normalize_name,
)

DEFAULT_MAX_TURNS = 25
_FIELDS = {
    "name",
    "description",
    "tools",
    "disallowedTools",
    "model",
    "maxTurns",
    "permissionMode",
    "background",
}


@dataclass(frozen=True)
class _Location:
    source: DefinitionSource
    root: Path
    fatal: bool = False


class AgentCatalog:
    def __init__(
        self,
        project_root: Path,
        user_root: Path,
        builtin_root: Path,
        definitions: dict[str, Definition],
        diagnostics: tuple[AgentDiagnostic, ...],
    ) -> None:
        self._project_root = project_root
        self._user_root = user_root
        self._builtin_root = builtin_root
        self._definitions = definitions
        self._diagnostics = diagnostics

    @classmethod
    def load(
        cls,
        root: Path,
        user_root: Path | None = None,
        builtin_root: Path | None = None,
    ) -> "AgentCatalog":
        project_root = root.resolve()
        user = (Path.home() / ".mewcode" / "agents") if user_root is None else user_root.resolve()
        builtin = _builtin_root() if builtin_root is None else builtin_root.resolve()
        locations = (
            _Location(DefinitionSource.BUILTIN, builtin, fatal=True),
            _Location(DefinitionSource.USER, user),
            _Location(DefinitionSource.PROJECT, project_root / ".mewcode" / "agents"),
        )
        definitions, diagnostics = _discover(locations)
        return cls(project_root, user, builtin, definitions, tuple(diagnostics))

    def resolve(self, name: str) -> Definition | None:
        return self._definitions.get(normalize_name(name))

    def effective(self) -> tuple[Definition, ...]:
        return tuple(self._definitions[name] for name in sorted(self._definitions))

    def diagnostics(self) -> tuple[AgentDiagnostic, ...]:
        return self._diagnostics

    def prompt_listing(self) -> str:
        return "\n".join(
            f"- `{definition.name}`: {definition.description}"
            for definition in self.effective()
        )

    @property
    def user_root(self) -> Path:
        return self._user_root


def parse_definition(path: Path, source: DefinitionSource) -> Definition:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DefinitionError(f"无法读取 Agent 定义: {exc}") from exc
    raw, instruction = _frontmatter(content)
    unknown = sorted(set(raw) - _FIELDS)
    if unknown:
        raise DefinitionError(f"存在未知字段: {', '.join(unknown)}")

    name = _required_string(raw, "name")
    if name != normalize_name(name) or NAME_RE.fullmatch(name) is None:
        raise DefinitionError("name 必须是 1-32 位小写 kebab-case")
    description = _required_string(raw, "description")
    if "\n" in description:
        raise DefinitionError("description 必须是一句话")
    tools = _tool_names(raw.get("tools"), "tools", required=False)
    disallowed = _tool_names(raw.get("disallowedTools", []), "disallowedTools", required=True)

    model_raw = raw.get("model", "inherit")
    if not isinstance(model_raw, str) or not model_raw.strip():
        raise DefinitionError("model 必须是 Provider 配置名称或 inherit")
    model_name = model_raw.strip()
    model_profile = None if model_name == "inherit" else model_name

    max_turns = raw.get("maxTurns", DEFAULT_MAX_TURNS)
    if isinstance(max_turns, bool) or not isinstance(max_turns, int) or max_turns <= 0:
        raise DefinitionError("maxTurns 必须是正整数")

    permission_raw = raw.get("permissionMode", PermissionMode.DEFAULT.value)
    try:
        permission_mode = PermissionMode(permission_raw)
    except (TypeError, ValueError) as exc:
        raise DefinitionError("permissionMode 无效") from exc

    background = raw.get("background", False)
    if not isinstance(background, bool):
        raise DefinitionError("background 必须是布尔值")

    return Definition(
        name=name,
        description=description,
        instruction=instruction,
        tools=tools,
        disallowed_tools=disallowed or frozenset(),
        model_profile=model_profile,
        max_turns=max_turns,
        permission_mode=permission_mode,
        background=background,
        source=source,
        path=path,
    )


def _discover(locations: tuple[_Location, ...]) -> tuple[dict[str, Definition], list[AgentDiagnostic]]:
    effective: dict[str, Definition] = {}
    diagnostics: list[AgentDiagnostic] = []
    for location in locations:
        source_definitions: dict[str, Definition] = {}
        for entry in _entries(location.root):
            try:
                definition = parse_definition(entry, location.source)
            except DefinitionError as exc:
                if location.fatal:
                    raise RuntimeError(f"内置 Agent 定义无效: {entry}: {exc}") from exc
                diagnostics.append(AgentDiagnostic(entry, str(exc)))
                continue
            if definition.name in source_definitions:
                diagnostics.append(AgentDiagnostic(entry, f"同一来源存在重复 Agent: {definition.name}"))
                continue
            source_definitions[definition.name] = definition
        effective.update(source_definitions)
    return effective, diagnostics


def _entries(root: Path) -> list[Path]:
    try:
        entries = tuple(root.iterdir())
    except OSError:
        return []
    try:
        return sorted(
            (path for path in entries if path.suffix.lower() == ".md" and path.is_file()),
            key=lambda path: path.name.lower(),
        )
    except OSError:
        return []


def _builtin_root() -> Path:
    resource = importlib.resources.files("mewcode.subagent").joinpath("builtin")
    return Path(str(resource))


def _frontmatter(content: str) -> tuple[dict[str, Any], str]:
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise DefinitionError("Agent 定义必须以 YAML frontmatter 开始")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() != "---":
            continue
        try:
            import yaml

            raw = yaml.safe_load("".join(lines[1:index]))
        except yaml.YAMLError as exc:
            raise DefinitionError(f"YAML frontmatter 格式错误: {exc}") from exc
        if not isinstance(raw, dict):
            raise DefinitionError("YAML frontmatter 必须是对象")
        instruction = "".join(lines[index + 1 :]).strip()
        if not instruction:
            raise DefinitionError("Agent 正文不能为空")
        return raw, instruction
    raise DefinitionError("Agent frontmatter 缺少结束标记")


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DefinitionError(f"{key} 必须是非空字符串")
    return value.strip()


def _tool_names(value: object, key: str, *, required: bool) -> frozenset[str] | None:
    if value is None and not required:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise DefinitionError(f"{key} 必须是工具名称列表")
    return frozenset(item.strip() for item in value)


__all__ = ["AgentCatalog", "parse_definition"]
