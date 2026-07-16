from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from mewcode.agent import Agent, Phase
from textual.widgets import Static, TextArea

from .timeline import ToolRun
from .view import (
    assistant_entry,
    error_entry,
    notice_entry,
    approval_block,
    streaming_block,
    tool_result_entry,
    tools_running_block,
)

if TYPE_CHECKING:
    from .app import MewCodeApp, SessionState


async def consume_stream(app: MewCodeApp) -> None:
    if app.provider is None:
        return

    try:
        agent = Agent(app.provider, app.registry, app.version, app.engine)
        cancel = app.turn_cancel if app.turn_cancel is not None else asyncio.Event()
        saw_error = False
        async for event in agent.run(app.conv, app.mode, cancel):
            if event.approval is not None:
                app.pending = event.approval
                app.approve_cursor = 0
                app.state = app.state.__class__.APPROVING
                refresh_approval_view(app)
                continue
            if event.err is not None:
                await app.append_timeline(error_entry(event.err))
                saw_error = True
                continue
            if event.tool is not None:
                if event.tool.phase is Phase.START:
                    await _start_tool(app, event.tool.name, event.tool.args)
                else:
                    await _finish_tool(
                        app,
                        event.tool.name,
                        event.tool.args,
                        event.tool.result,
                        event.tool.is_error,
                    )
            if event.usage is not None:
                app.usage_in += event.usage.input
                app.usage_out += event.usage.output
                app.refresh_status()
            if event.notice:
                await app.append_timeline(notice_entry(event.notice))
            if event.iter:
                app.iter = event.iter
                refresh_streaming_view(app)
            if event.done:
                if saw_error:
                    _finish_turn(app)
                else:
                    await finish_with_assistant(app, app.cur_reply, save=False)
                return
            if event.text:
                app.cur_reply += event.text
                refresh_streaming_view(app)
        _finish_turn(app)
    except Exception as exc:
        await finish_with_error(app, exc)


def tick(app: MewCodeApp, streaming_state: SessionState) -> None:
    if app.state is streaming_state:
        refresh_streaming_view(app)


def refresh_streaming_view(app: MewCodeApp) -> None:
    elapsed = _elapsed_seconds(app)
    if app.cur_tools:
        block = tools_running_block(
            [(tool.name, tool.args) for tool in app.cur_tools], elapsed
        )
    else:
        block = streaming_block(app.cur_reply, elapsed, app.iter)
    app.query_one("#streaming", Static).update(block)


def refresh_approval_view(app: MewCodeApp) -> None:
    if app.pending is None:
        return
    app.query_one("#streaming", Static).update(
        approval_block(
            app.pending.name,
            app.pending.args,
            app.pending.reason,
            app.approve_cursor,
        )
    )


async def finish_with_assistant(
    app: MewCodeApp, reply: str, *, save: bool = True
) -> None:
    elapsed = _elapsed_seconds(app)
    if reply:
        await app.append_timeline(assistant_entry(reply, elapsed))
    if save:
        app.conv.add_assistant(reply)
    _finish_turn(app)


async def finish_with_error(app: MewCodeApp, err: Exception) -> None:
    await app.append_timeline(error_entry(err))
    _finish_turn(app)


def _finish_turn(app: MewCodeApp) -> None:
    if app._timer is not None:
        app._timer.stop()
    app._timer = None
    app._stream_task = None
    app.cur_reply = ""
    app.cur_tools = []
    app.iter = 0
    app.turn_cancel = None
    app.pending = None
    app.approve_cursor = 0
    app.state = app.state.__class__.IDLE
    app.query_one("#streaming", Static).update("")
    input_area = app.query_one("#input", TextArea)
    input_area.read_only = False
    input_area.focus()


def _elapsed_seconds(app: MewCodeApp) -> int:
    return max(0, int(time.monotonic() - app.turn_start))


async def _start_tool(app: MewCodeApp, name: str, args: str) -> None:
    if app.cur_reply:
        await app.append_timeline(
            assistant_entry(app.cur_reply, _elapsed_seconds(app))
        )
        app.cur_reply = ""
    app.cur_tools.append(ToolRun(name, args))
    refresh_streaming_view(app)


async def _finish_tool(
    app: MewCodeApp,
    name: str,
    args: str,
    result: str,
    is_error: bool,
) -> None:
    tool = app.cur_tools.pop(0) if app.cur_tools else ToolRun(name, args)
    await app.append_timeline(
        tool_result_entry(tool.name, tool.args, result, is_error)
    )
    refresh_streaming_view(app)
