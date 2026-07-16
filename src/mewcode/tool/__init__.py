from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from mewcode.llm import ToolDefinition

DEFAULT_TIMEOUT = 30.0
TRUNCATED_MARKER = "\n[truncated]"


@dataclass(frozen=True)
class Result:
    content: str
    is_error: bool = False


@runtime_checkable
class Tool(Protocol):
    read_only: bool

    def name(self) -> str: ...

    def description(self) -> str: ...

    def parameters(self) -> dict[str, Any]: ...

    async def execute(self, args: str) -> Result: ...


class Registry:
    def __init__(self) -> None:
        self._order: list[str] = []
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.name()
        if not name:
            raise ValueError("工具名不能为空")
        if name in self._tools:
            raise ValueError(f"工具已注册: {name}")
        self._order.append(name)
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=self._tools[name].description(),
                input_schema=self._tools[name].parameters(),
            )
            for name in self._order
        ]

    def read_only_definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=self._tools[name].description(),
                input_schema=self._tools[name].parameters(),
            )
            for name in self._order
            if getattr(self._tools[name], "read_only", False) is True
        ]

    def is_read_only(self, name: str) -> bool:
        tool = self.get(name)
        return bool(tool is not None and getattr(tool, "read_only", False))

    async def execute(
        self,
        name: str,
        args: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> Result:
        tool = self.get(name)
        if tool is None:
            return error_result("unknown_tool", f"未知工具: {name}")

        normalized_args = args.strip() or "{}"
        try:
            return await asyncio.wait_for(
                tool.execute(normalized_args), timeout=timeout
            )
        except TimeoutError:
            return error_result("timeout", f"工具 {name} 执行超时（{timeout:g} 秒）")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return error_result("internal_error", f"工具 {name} 执行失败: {exc}")


def parse_arguments(args: str) -> tuple[dict[str, Any] | None, Result | None]:
    try:
        value = json.loads(args or "{}")
    except json.JSONDecodeError as exc:
        return None, error_result("invalid_json", f"工具参数不是有效 JSON: {exc.msg}")
    if not isinstance(value, dict):
        return None, error_result("invalid_arguments", "工具参数必须是 JSON 对象")
    return value, None


def require_string(
    values: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> tuple[str | None, Result | None]:
    value = values.get(key)
    if not isinstance(value, str):
        return None, error_result("invalid_arguments", f"参数 {key} 必须是字符串")
    if not allow_empty and not value:
        return None, error_result("invalid_arguments", f"参数 {key} 不能为空")
    return value, None


def error_result(code: str, message: str) -> Result:
    return Result(
        content=json.dumps(
            {"ok": False, "error": {"code": code, "message": message}},
            ensure_ascii=False,
        ),
        is_error=True,
    )


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    keep = max(0, limit - len(TRUNCATED_MARKER))
    return text[:keep] + TRUNCATED_MARKER, True


def new_default_registry() -> Registry:
    from .bash import BashTool
    from .edit_file import EditFileTool
    from .glob_tool import GlobTool
    from .grep_tool import GrepTool
    from .read_file import ReadFileTool
    from .write_file import WriteFileTool

    registry = Registry()
    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
    ):
        registry.register(tool)
    return registry


__all__ = [
    "DEFAULT_TIMEOUT",
    "Registry",
    "Result",
    "Tool",
    "error_result",
    "new_default_registry",
    "parse_arguments",
    "require_string",
    "truncate",
]
