"""MCP server connection and lifecycle management."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass

import httpx
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from .config import Config, ServerConfig
from .tool import McpTool, adapt_tool

connect_timeout = 30.0
close_timeout = 5.0


@dataclass(frozen=True)
class _Session:
    name: str
    session: ClientSession


class Manager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: list[_Session] = []
        self._tools: list[McpTool] = []
        self._stack = AsyncExitStack()

    def tools(self) -> list[McpTool]:
        return list(self._tools)

    async def close(self) -> None:
        try:
            await asyncio.wait_for(self._stack.aclose(), timeout=close_timeout)
        except asyncio.TimeoutError:
            _warn("close timeout, some sessions may leak")
        except Exception as exc:
            _warn(f"close failed: {type(exc).__name__}")


async def new_manager(cfg: Config, version: str) -> Manager:
    manager = Manager()
    tasks = [
        asyncio.create_task(_connect_one(manager, name, config, version))
        for name, config in cfg.servers.items()
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    manager._tools.sort(key=lambda tool: tool.full_name)
    return manager


async def _connect_one(
    manager: Manager, name: str, config: ServerConfig, version: str
) -> None:
    try:
        await asyncio.wait_for(
            _do_connect(manager, name, config, version), timeout=connect_timeout
        )
    except asyncio.TimeoutError:
        _warn(f"connect server {name} timeout after {connect_timeout:g}s")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _warn(f"connect server {name} failed: {type(exc).__name__}")


async def _do_connect(
    manager: Manager, name: str, config: ServerConfig, version: str
) -> None:
    async with AsyncExitStack() as attempt_stack:
        transport_context = await _transport(config, attempt_stack)
        transport = await attempt_stack.enter_async_context(transport_context)
        read_stream, write_stream = transport[0], transport[1]
        session = await attempt_stack.enter_async_context(
            ClientSession(
                read_stream,
                write_stream,
                client_info=types.Implementation(name="mewcode", version=version),
            )
        )
        await session.initialize()
        listed = await session.list_tools()
        tools = _adapt_tools(name, listed.tools, session)
        retained_stack = attempt_stack.pop_all()

    async with manager._lock:
        manager._stack.push_async_callback(retained_stack.aclose)
        manager._sessions.append(_Session(name, session))
        manager._tools.extend(tools)


async def _transport(config: ServerConfig, stack: AsyncExitStack):
    if config.type == "stdio":
        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env={**os.environ, **config.env},
        )
        return stdio_client(params)
    client = await stack.enter_async_context(httpx.AsyncClient(headers=config.headers))
    return streamable_http_client(config.url, http_client=client)


def _adapt_tools(
    server_name: str, remote_tools: list[types.Tool], session: ClientSession
) -> list[McpTool]:
    adapted: dict[str, McpTool] = {}
    for remote_tool in remote_tools:
        tool = adapt_tool(server_name, remote_tool, session)
        if tool is None:
            continue
        if tool.remote_name in adapted:
            _warn(
                f"server {server_name} returned duplicate tool {tool.remote_name}; keeping last"
            )
        adapted[tool.remote_name] = tool
    return list(adapted.values())


def _warn(message: str) -> None:
    print(f"[mcp] warn: {message}", file=sys.stderr)
