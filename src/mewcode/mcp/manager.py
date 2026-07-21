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
        self._close_event = asyncio.Event()
        self._connection_tasks: list[asyncio.Task[None]] = []
        self._closing = False

    def tools(self) -> list[McpTool]:
        return list(self._tools)

    async def close(self) -> None:
        async with self._lock:
            self._closing = True
            self._close_event.set()
            tasks = list(self._connection_tasks)

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=close_timeout
            )
        except asyncio.TimeoutError:
            _warn("close timeout, some sessions may leak")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:
            _warn(f"close failed: {type(exc).__name__}")
        else:
            for result in results:
                if isinstance(result, Exception):
                    _warn(f"close failed: {type(result).__name__}")
        finally:
            async with self._lock:
                self._sessions.clear()
                self._tools.clear()
                self._connection_tasks.clear()


async def new_manager(cfg: Config, version: str) -> Manager:
    manager = Manager()
    ready = [asyncio.get_running_loop().create_future() for _ in cfg.servers]
    manager._connection_tasks = [
        asyncio.create_task(_connect_one(manager, name, config, version, signal))
        for (name, config), signal in zip(cfg.servers.items(), ready, strict=True)
    ]
    if ready:
        await asyncio.gather(*ready, return_exceptions=True)
    manager._tools.sort(key=lambda tool: tool.full_name)
    return manager


async def _connect_one(
    manager: Manager,
    name: str,
    config: ServerConfig,
    version: str,
    ready: asyncio.Future[None],
) -> None:
    try:
        async with AsyncExitStack() as stack:
            async with asyncio.timeout(connect_timeout):
                session, tools = await _do_connect(name, config, version, stack)

            async with manager._lock:
                if manager._closing:
                    return
                manager._sessions.append(_Session(name, session))
                manager._tools.extend(tools)
            ready.set_result(None)
            await manager._close_event.wait()
    except asyncio.TimeoutError:
        _warn(f"connect server {name} timeout after {connect_timeout:g}s")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _warn(f"connect server {name} failed: {type(exc).__name__}")
    finally:
        if not ready.done():
            ready.set_result(None)


async def _do_connect(
    name: str, config: ServerConfig, version: str, stack: AsyncExitStack
) -> tuple[ClientSession, list[McpTool]]:
    transport_context = await _transport(config, stack)
    transport = await stack.enter_async_context(transport_context)
    read_stream, write_stream = transport[0], transport[1]
    session = await stack.enter_async_context(
        ClientSession(
            read_stream,
            write_stream,
            client_info=types.Implementation(name="mewcode", version=version),
        )
    )
    await session.initialize()
    listed = await session.list_tools()
    return session, _adapt_tools(name, listed.tools, session)


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
