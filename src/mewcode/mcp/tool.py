"""Adapt MCP tools to MewCode's existing tool protocol."""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from typing import Any, Protocol

from mcp import types

from mewcode.tool import Result, error_result, parse_arguments

CALL_TIMEOUT = 30.0
_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_non_text_warned: set[str] = set()


class CallerSession(Protocol):
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> types.CallToolResult: ...


@dataclass
class McpTool:
    full_name: str
    remote_name: str
    tool_description: str
    input_schema: dict[str, Any]
    read_only: bool
    caller: CallerSession

    def name(self) -> str:
        return self.full_name

    def description(self) -> str:
        return self.tool_description

    def parameters(self) -> dict[str, Any]:
        return self.input_schema

    async def execute(self, args: str) -> Result:
        arguments, error = parse_arguments(args)
        if error is not None:
            return error
        try:
            result = await asyncio.wait_for(
                self.caller.call_tool(self.remote_name, arguments or None),
                timeout=CALL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return error_result("timeout", "MCP 工具调用超时（30 秒）")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return error_result("mcp_error", f"MCP 工具调用失败: {exc}")

        texts: list[str] = []
        dropped_non_text = False
        for block in result.content:
            if isinstance(block, types.TextContent):
                texts.append(block.text)
            else:
                dropped_non_text = True
        if dropped_non_text and self.full_name not in _non_text_warned:
            _non_text_warned.add(self.full_name)
            print(
                f"[mcp] warn: tool {self.full_name} returned non-text content blocks (dropped)",
                file=sys.stderr,
            )
        return Result("\n".join(texts), is_error=bool(result.isError))


def adapt_tool(
    server_name: str, remote_tool: types.Tool, session: CallerSession
) -> McpTool | None:
    full_name = f"mcp__{server_name}__{remote_tool.name}"
    if _VALID_NAME.fullmatch(full_name) is None:
        print(
            f"[mcp] warn: skip tool {full_name}: name contains illegal characters",
            file=sys.stderr,
        )
        return None
    schema = remote_tool.inputSchema
    parameters = (
        dict(schema) if isinstance(schema, dict) and schema else {"type": "object"}
    )
    annotations = remote_tool.annotations
    read_only = bool(annotations is not None and annotations.readOnlyHint is True)
    description = (
        remote_tool.description
        or f"来自 MCP server {server_name} 的工具 {remote_tool.name}"
    )
    return McpTool(
        full_name=full_name,
        remote_name=remote_tool.name,
        tool_description=description,
        input_schema=parameters,
        read_only=read_only,
        caller=session,
    )
