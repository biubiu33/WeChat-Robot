"""Capability filtering for child agents."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any

from mewcode.tool import DEFAULT_TIMEOUT, Registry, Result, Tool, ToolDefinition, error_result

from .cache import FileReadCache
from .model import Definition

CONTROL_PLANE_TOOLS = frozenset(
    {
        "Agent",
        "TaskList",
        "TaskGet",
        "TaskStop",
        "SendMessage",
        "agent",
        "task_list",
        "task_get",
        "task_stop",
        "send_message",
    }
)
BACKGROUND_ALLOWLIST = frozenset(
    {"read_file", "write_file", "edit_file", "bash", "glob", "grep", "load_skill"}
)


def allowed_tools(
    base: Registry,
    definition: Definition,
    *,
    background: bool,
    parent_allowed: Collection[str] | None = None,
) -> frozenset[str]:
    """Calculate the final child-visible tools without trusting Registry system bypasses."""

    available = {item.name for item in base.definitions()}
    if parent_allowed is not None:
        available.intersection_update(parent_allowed)
    available.difference_update(CONTROL_PLANE_TOOLS)
    if background:
        available.intersection_update(BACKGROUND_ALLOWLIST)
    available.difference_update(definition.disallowed_tools)
    if definition.tools is not None:
        available.intersection_update(definition.tools)
    return frozenset(available)


def child_safe_skill_mode(skill: Any) -> Result | None:
    """Reject nested fork Skills while preserving normal inline Skill behavior."""

    mode = getattr(getattr(skill, "metadata", skill), "mode", None)
    if mode == "fork" or getattr(mode, "value", None) == "fork":
        return error_result("nested_agent_denied", "Sub-agents cannot run fork Skills")
    return None


class ScopedRegistry:
    """A non-copying but non-bypassable child view over a shared registry."""

    def __init__(
        self,
        base: Registry,
        allowed: Collection[str],
        *,
        cache: FileReadCache | None = None,
        path_resolver: Callable[[str], Path] | None = None,
        overrides: dict[str, Tool] | None = None,
    ) -> None:
        self._base = base
        self._allowed = frozenset(allowed)
        self._cache = cache if cache is not None else FileReadCache()
        self._path_resolver = path_resolver or _default_path_resolver
        self._overrides = dict(overrides or {})

    def definitions(
        self, allowed_tools: Collection[str] | None = None
    ) -> list[ToolDefinition]:
        allowed = self._intersect(allowed_tools)
        return [self._definition(item.name) for item in self._base.definitions() if item.name in allowed]

    def read_only_definitions(
        self, allowed_tools: Collection[str] | None = None
    ) -> list[ToolDefinition]:
        allowed = self._intersect(allowed_tools)
        return [
            self._definition(item.name)
            for item in self._base.read_only_definitions()
            if item.name in allowed and self.is_read_only(item.name)
        ]

    def get(self, name: str) -> Tool | None:
        if name not in self._allowed:
            return None
        return self._overrides.get(name) or self._base.get(name)

    def is_read_only(self, name: str) -> bool:
        tool = self.get(name)
        return bool(tool is not None and getattr(tool, "read_only", False))

    def is_system(self, name: str) -> bool:
        tool = self.get(name)
        return bool(tool is not None and getattr(tool, "system", False))

    def ordinary_names(self) -> tuple[str, ...]:
        return tuple(name for name in self._base.ordinary_names() if name in self._allowed)

    async def execute(
        self,
        name: str,
        args: str,
        timeout: float = DEFAULT_TIMEOUT,
        allowed_tools: Collection[str] | None = None,
    ) -> Result:
        if name not in self._intersect(allowed_tools):
            return error_result("tool_not_allowed", f"Sub-agent cannot use tool: {name}")

        path = _path_argument(args, self._path_resolver)
        if name == "read_file" and path is not None:
            cached = await self._cache.get(path)
            if cached is not None:
                return cached

        override = self._overrides.get(name)
        if override is None:
            result = await self._base.execute(name, args, timeout, self._allowed)
        else:
            try:
                result = await asyncio.wait_for(override.execute(args.strip() or "{}"), timeout)
            except TimeoutError:
                result = error_result("timeout", f"Tool timed out: {name}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                result = error_result("internal_error", f"Tool failed: {exc}")
        if result.is_error or path is None:
            return result
        if name == "read_file":
            self._cache.put(path, result)
        elif name in {"write_file", "edit_file"}:
            self._cache.invalidate(path)
        return result

    def _intersect(self, requested: Collection[str] | None) -> frozenset[str]:
        if requested is None:
            return self._allowed
        return self._allowed.intersection(requested)

    def _definition(self, name: str) -> ToolDefinition:
        tool = self.get(name)
        assert tool is not None
        return ToolDefinition(name, tool.description(), tool.parameters())


def _path_argument(args: str, resolver: Callable[[str], Path]) -> Path | None:
    try:
        values = json.loads(args or "{}")
    except json.JSONDecodeError:
        return None
    path = values.get("path") if isinstance(values, dict) else None
    if not isinstance(path, str) or not path:
        return None
    try:
        return resolver(path)
    except (OSError, ValueError):
        return None


def _default_path_resolver(value: str) -> Path:
    return Path(value).expanduser().resolve(strict=False)


__all__ = [
    "BACKGROUND_ALLOWLIST",
    "CONTROL_PLANE_TOOLS",
    "ScopedRegistry",
    "allowed_tools",
    "child_safe_skill_mode",
]
