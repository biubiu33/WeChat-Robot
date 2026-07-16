from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps
from types import SimpleNamespace
from typing import Any, TypeVar

from mcp import types

import mewcode.mcp.tool as mcp_tool
from mewcode.mcp.tool import adapt_tool

F = TypeVar("F", bound=Callable[..., Any])


def async_test(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(func(*args, **kwargs))

    return wrapper  # type: ignore[return-value]


class Caller:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> object:
        self.calls.append((name, arguments))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def remote_tool(name: str = "search", **kwargs: Any) -> types.Tool:
    return types.Tool(name=name, inputSchema={"type": "object"}, **kwargs)


@async_test
async def test_adapted_tool_preserves_protocol_and_text_results() -> None:
    caller = Caller(
        types.CallToolResult(
            content=[
                types.TextContent(type="text", text="first"),
                types.TextContent(type="text", text="second"),
            ]
        )
    )
    tool = adapt_tool(
        "demo",
        remote_tool(
            description="Search data",
            annotations=types.ToolAnnotations(readOnlyHint=True),
        ),
        caller,
    )

    assert tool is not None
    assert tool.name() == "mcp__demo__search"
    assert tool.description() == "Search data"
    assert tool.parameters() == {"type": "object"}
    assert tool.read_only is True
    result = await tool.execute('{"query":"mewcode"}')

    assert result.content == "first\nsecond"
    assert not result.is_error
    assert caller.calls == [("search", {"query": "mewcode"})]


@async_test
async def test_invalid_arguments_do_not_call_remote_tool() -> None:
    caller = Caller(types.CallToolResult(content=[]))
    tool = adapt_tool("demo", remote_tool(), caller)

    assert tool is not None
    result = await tool.execute("[]")

    assert result.is_error
    assert "invalid_arguments" in result.content
    assert caller.calls == []


@async_test
async def test_remote_error_exception_and_timeout_become_results(
    monkeypatch: Any,
) -> None:
    remote_error = Caller(types.CallToolResult(content=[], isError=True))
    tool = adapt_tool("demo", remote_tool(), remote_error)
    assert tool is not None
    assert (await tool.execute("{}")).is_error

    failed = adapt_tool("demo", remote_tool("broken"), Caller(RuntimeError("offline")))
    assert failed is not None
    failure = await failed.execute("{}")
    assert failure.is_error and "mcp_error" in failure.content

    class SlowCaller(Caller):
        async def call_tool(
            self, name: str, arguments: dict[str, Any] | None = None
        ) -> object:
            await asyncio.sleep(1)
            return types.CallToolResult(content=[])

    monkeypatch.setattr(mcp_tool, "CALL_TIMEOUT", 0.01)
    slow = adapt_tool("demo", remote_tool("slow"), SlowCaller(None))
    assert slow is not None
    timeout = await slow.execute("{}")
    assert timeout.is_error and "timeout" in timeout.content


@async_test
async def test_non_text_content_warns_once_and_is_dropped(capsys: Any) -> None:
    mcp_tool._non_text_warned.clear()
    caller = Caller(
        SimpleNamespace(
            content=[types.TextContent(type="text", text="kept"), object()],
            isError=False,
        )
    )
    tool = adapt_tool("demo", remote_tool(), caller)
    assert tool is not None

    assert (await tool.execute("{}")).content == "kept"
    assert (await tool.execute("{}")).content == "kept"

    assert capsys.readouterr().err.count("non-text") == 1


def test_illegal_name_is_skipped_and_empty_description_falls_back(capsys: Any) -> None:
    caller = Caller(types.CallToolResult(content=[]))

    invalid = adapt_tool("bad server", remote_tool(), caller)
    fallback = adapt_tool("demo", remote_tool("plain"), caller)

    assert invalid is None
    assert fallback is not None
    assert "来自 MCP server demo" in fallback.description()
    assert "illegal characters" in capsys.readouterr().err
