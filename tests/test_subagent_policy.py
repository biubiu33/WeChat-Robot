from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from mewcode.skill import Skill, SkillMetadata, SkillMode, SkillSource
from mewcode.subagent import (
    Definition,
    DefinitionSource,
    PermissionMode,
    ScopedRegistry,
    allowed_tools,
    child_safe_skill_mode,
)
from mewcode.tool import Registry, Result


class RecordingTool:
    def __init__(self, name: str, *, system: bool = False, read_only: bool = False) -> None:
        self._name = name
        self.system = system
        self.read_only = read_only
        self.calls = 0

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return self._name

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        self.calls += 1
        return Result(f"ran {self._name}")


def definition(
    *, tools: frozenset[str] | None = None, disallowed: frozenset[str] = frozenset()
) -> Definition:
    return Definition(
        name="test",
        description="test role",
        instruction="complete the task",
        tools=tools,
        disallowed_tools=disallowed,
        model_profile=None,
        max_turns=5,
        permission_mode=PermissionMode.DEFAULT,
        background=False,
        source=DefinitionSource.BUILTIN,
        path=Path("definition.md"),
    )


def test_allowed_tools_applies_all_layers() -> None:
    registry = Registry()
    for name, system in (
        ("read_file", False),
        ("write_file", False),
        ("load_skill", True),
        ("Agent", True),
        ("TaskGet", True),
    ):
        registry.register(RecordingTool(name, system=system))

    permitted = allowed_tools(
        registry,
        definition(tools=frozenset({"read_file", "write_file", "Agent"})),
        background=True,
        parent_allowed={"read_file", "write_file", "load_skill", "Agent", "TaskGet"},
    )

    assert permitted == frozenset({"read_file", "write_file"})


def test_role_disallowed_tool_wins_over_whitelist() -> None:
    registry = Registry()
    registry.register(RecordingTool("read_file", read_only=True))

    permitted = allowed_tools(
        registry,
        definition(tools=frozenset({"read_file"}), disallowed=frozenset({"read_file"})),
        background=False,
    )

    assert permitted == frozenset()


def test_scoped_registry_never_leaks_system_or_control_tools() -> None:
    registry = Registry()
    read = RecordingTool("read_file", read_only=True)
    load_skill = RecordingTool("load_skill", system=True)
    agent = RecordingTool("Agent", system=True)
    registry.register(read)
    registry.register(load_skill)
    registry.register(agent)
    scoped = ScopedRegistry(registry, {"read_file"})

    assert [item.name for item in scoped.definitions()] == ["read_file"]
    assert scoped.get("load_skill") is None
    assert scoped.get("Agent") is None
    result = asyncio.run(scoped.execute("load_skill", "{}"))

    assert result.is_error
    assert load_skill.calls == 0


def test_scoped_registry_rechecks_per_request_restriction() -> None:
    registry = Registry()
    read = RecordingTool("read_file", read_only=True)
    registry.register(read)
    scoped = ScopedRegistry(registry, {"read_file"})

    result = asyncio.run(scoped.execute("read_file", "{}", allowed_tools=set()))

    assert result.is_error
    assert read.calls == 0


def test_child_rejects_only_nested_fork_skills(tmp_path: Path) -> None:
    fork = Skill(
        SkillMetadata("fork", "fork", frozenset(), SkillMode.FORK, "none"),
        SkillSource.USER,
        tmp_path / "fork.md",
        tmp_path,
    )
    inline = Skill(
        SkillMetadata("inline", "inline", frozenset(), SkillMode.INLINE, "none"),
        SkillSource.USER,
        tmp_path / "inline.md",
        tmp_path,
    )

    denied = child_safe_skill_mode(fork)

    assert denied is not None and denied.is_error
    assert "nested_agent_denied" in denied.content
    assert child_safe_skill_mode(inline) is None
