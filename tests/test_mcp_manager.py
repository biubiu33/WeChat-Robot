from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from functools import wraps
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import Any, TypeVar

from mcp import types

import mewcode.mcp.manager as manager_module
from mewcode.mcp.config import Config, ServerConfig

F = TypeVar("F", bound=Callable[..., Any])


def async_test(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(func(*args, **kwargs))

    return wrapper  # type: ignore[return-value]


class Transport(AbstractAsyncContextManager[tuple[str, object]]):
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.closed = False

    async def __aenter__(self) -> tuple[str, object]:
        return self.marker, object()

    async def __aexit__(self, *args: object) -> None:
        self.closed = True


class Session(AbstractAsyncContextManager["Session"]):
    def __init__(
        self, marker: str, tools: list[types.Tool], fail: bool = False
    ) -> None:
        self.marker = marker
        self._tools = tools
        self._fail = fail
        self.closed = False

    async def __aenter__(self) -> "Session":
        return self

    async def __aexit__(self, *args: object) -> None:
        self.closed = True

    async def initialize(self) -> None:
        if self._fail:
            raise RuntimeError("unavailable")

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(tools=self._tools)

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> object:
        return types.CallToolResult(content=[])


def tool(name: str) -> types.Tool:
    return types.Tool(name=name, inputSchema={"type": "object"})


@async_test
async def test_connects_sorts_tools_and_closes_only_successes(
    monkeypatch: Any, capsys: Any
) -> None:
    transports: dict[str, Transport] = {}
    sessions: dict[str, Session] = {}
    listed = {
        "alpha": [tool("zeta"), tool("alpha"), tool("alpha")],
        "beta": [tool("same")],
        "broken": [],
    }

    async def transport(config: ServerConfig, stack: object) -> Transport:
        result = Transport(config.command)
        transports[config.command] = result
        return result

    def session_factory(read: str, write: object, **kwargs: object) -> Session:
        result = Session(read, listed[read], fail=read == "broken")
        sessions[read] = result
        return result

    monkeypatch.setattr(manager_module, "_transport", transport)
    monkeypatch.setattr(manager_module, "ClientSession", session_factory)
    config = Config(
        {
            "alpha": ServerConfig(type="stdio", command="alpha"),
            "broken": ServerConfig(type="stdio", command="broken"),
            "beta": ServerConfig(type="stdio", command="beta"),
        }
    )

    manager = await manager_module.new_manager(config, "1.0")

    assert [item.name() for item in manager.tools()] == [
        "mcp__alpha__alpha",
        "mcp__alpha__zeta",
        "mcp__beta__same",
    ]
    assert sessions["broken"].closed and transports["broken"].closed
    assert not sessions["alpha"].closed and not transports["alpha"].closed
    assert "duplicate tool alpha" in capsys.readouterr().err

    await manager.close()

    assert sessions["alpha"].closed and transports["alpha"].closed
    assert sessions["beta"].closed and transports["beta"].closed


@async_test
async def test_connection_timeout_is_isolated(monkeypatch: Any, capsys: Any) -> None:
    original_timeout = manager_module.connect_timeout

    async def slow(*args: object) -> None:
        await asyncio.sleep(1)

    monkeypatch.setattr(manager_module, "_do_connect", slow)
    monkeypatch.setattr(manager_module, "connect_timeout", 0.01)
    try:
        manager = await manager_module.new_manager(
            Config({"slow": ServerConfig(type="stdio", command="slow")}), "1.0"
        )
    finally:
        monkeypatch.setattr(manager_module, "connect_timeout", original_timeout)

    assert manager.tools() == []
    assert "connect server slow timeout" in capsys.readouterr().err


@async_test
async def test_close_timeout_does_not_block(monkeypatch: Any, capsys: Any) -> None:
    async def slow_connection() -> None:
        await asyncio.sleep(1)

    original_timeout = manager_module.close_timeout
    manager = manager_module.Manager()
    task = asyncio.create_task(slow_connection())
    manager._connection_tasks = [task]
    monkeypatch.setattr(manager_module, "close_timeout", 0.01)
    try:
        await manager.close()
    finally:
        monkeypatch.setattr(manager_module, "close_timeout", original_timeout)

    assert "close timeout" in capsys.readouterr().err
    assert task.cancelled()


@async_test
async def test_stdio_transport_merges_environment(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    def fake_stdio(params: object) -> object:
        captured["params"] = params
        return object()

    monkeypatch.setenv("HOST_VALUE", "host")
    monkeypatch.setattr(manager_module, "stdio_client", fake_stdio)

    from contextlib import AsyncExitStack

    stack = AsyncExitStack()
    await manager_module._transport(
        ServerConfig(
            type="stdio",
            command="server",
            args=["--run"],
            env={"HOST_VALUE": "override", "TOKEN": "secret"},
        ),
        stack,
    )
    await stack.aclose()

    params = captured["params"]
    assert getattr(params, "command") == "server"
    assert getattr(params, "args") == ["--run"]
    assert getattr(params, "env")["HOST_VALUE"] == "override"
    assert getattr(params, "env")["TOKEN"] == "secret"


@async_test
async def test_http_transport_passes_configured_headers(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}

    class FakeHttpClient(AbstractAsyncContextManager["FakeHttpClient"]):
        def __init__(self, *, headers: dict[str, str]) -> None:
            self.headers = headers
            self.closed = False

        async def __aenter__(self) -> "FakeHttpClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            self.closed = True

    def fake_http(url: str, *, http_client: FakeHttpClient) -> object:
        captured["url"] = url
        captured["client"] = http_client
        return object()

    monkeypatch.setattr(manager_module.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(manager_module, "streamable_http_client", fake_http)

    from contextlib import AsyncExitStack

    stack = AsyncExitStack()
    await manager_module._transport(
        ServerConfig(
            type="http",
            url="https://example.test/mcp",
            headers={"Authorization": "Bearer secret"},
        ),
        stack,
    )

    client = captured["client"]
    assert captured["url"] == "https://example.test/mcp"
    assert isinstance(client, FakeHttpClient)
    assert client.headers == {"Authorization": "Bearer secret"}
    await stack.aclose()
    assert client.closed


@async_test
async def test_stdio_server_end_to_end(capsys: Any) -> None:
    script = Path(__file__).parent / "fixtures" / "stdio_mcp_server.py"
    config = Config(
        {
            "fixture": ServerConfig(
                type="stdio",
                command=sys.executable,
                args=[str(script)],
                env={"MCP_TEST_VALUE": "configured"},
            )
        }
    )

    manager = await manager_module.new_manager(config, "1.0")
    try:
        tools = manager.tools()
        assert [tool.name() for tool in tools] == ["mcp__fixture__echo"]
        assert tools[0].read_only
        result = await tools[0].execute('{"value":"hello"}')
        assert result.content == "configured:hello"
        assert not result.is_error
    finally:
        await manager.close()

    assert "close failed" not in capsys.readouterr().err


@async_test
async def test_streamable_http_server_end_to_end(capsys: Any) -> None:
    script = Path(__file__).parent / "fixtures" / "http_mcp_server.py"
    port = _unused_port()
    environment = {**os.environ, "MCP_TEST_PORT": str(port)}
    process = subprocess.Popen(
        [sys.executable, str(script)],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        await asyncio.to_thread(_wait_for_port, port)
        config = Config(
            {
                "fixture": ServerConfig(
                    type="http",
                    url=f"http://127.0.0.1:{port}/mcp",
                    headers={"Authorization": "Bearer test-token"},
                )
            }
        )
        manager = await manager_module.new_manager(config, "1.0")
        try:
            tools = manager.tools()
            assert [tool.name() for tool in tools] == ["mcp__fixture__echo"]
            result = await tools[0].execute('{"value":"hello"}')
            assert result.content == "http:hello"
            assert not result.is_error
        finally:
            await manager.close()
        assert "close failed" not in capsys.readouterr().err
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_port(port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"HTTP MCP fixture did not listen on port {port}")
