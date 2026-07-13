from __future__ import annotations

import time
from typing import TYPE_CHECKING

from mewcode.agent import Agent, Phase
from textual.widgets import RichLog, Static, TextArea

from .view import (
    assistant_block,
    error_block,
    streaming_block,
    tool_line,
    tool_result_summary,
    tool_running_block,
)

if TYPE_CHECKING:
    from .app import MewCodeApp, SessionState


async def consume_stream(app: MewCodeApp) -> None:
    if app.provider is None:
        return

    try:
        agent = Agent(app.provider, app.registry)
        async for event in agent.run(app.conv):
            if event.err is not None:
                finish_with_error(app, event.err)
                return
            if event.text:
                app.cur_reply += event.text
                refresh_streaming_view(app)
            if event.tool is not None:
                if event.tool.phase is Phase.START:
                    _start_tool(app, event.tool.name, event.tool.args)
                else:
                    _finish_tool(
                        app,
                        event.tool.name,
                        event.tool.args,
                        event.tool.result,
                        event.tool.is_error,
                    )
            if event.done:
                finish_with_assistant(app, app.cur_reply, save=False)
                return
    except Exception as exc:
        finish_with_error(app, exc)


def tick(app: MewCodeApp, streaming_state: SessionState) -> None:
    if app.state is streaming_state:
        refresh_streaming_view(app)


def refresh_streaming_view(app: MewCodeApp) -> None:
    elapsed = _elapsed_seconds(app)
    if app.cur_tool is not None:
        name, args = app.cur_tool
        block = tool_running_block(name, args, elapsed)
    else:
        block = streaming_block(app.cur_reply, elapsed)
    app.query_one("#streaming", Static).update(block)


def finish_with_assistant(app: MewCodeApp, reply: str, *, save: bool = True) -> None:
    elapsed = _elapsed_seconds(app)
    if reply:
        app.query_one("#log", RichLog).write(assistant_block(reply, elapsed))
    if save:
        app.conv.add_assistant(reply)
    _finish_turn(app)


def finish_with_error(app: MewCodeApp, err: Exception) -> None:
    app.query_one("#log", RichLog).write(error_block(err))
    _finish_turn(app)


def _finish_turn(app: MewCodeApp) -> None:
    if app._timer is not None:
        app._timer.stop()
    app._timer = None
    app._stream_task = None
    app.cur_reply = ""
    app.cur_tool = None
    app.state = app.state.__class__.IDLE
    app.query_one("#streaming", Static).update("")
    input_area = app.query_one("#input", TextArea)
    input_area.read_only = False
    input_area.focus()


def _elapsed_seconds(app: MewCodeApp) -> int:
    return max(0, int(time.monotonic() - app.turn_start))


def _start_tool(app: MewCodeApp, name: str, args: str) -> None:
    if app.cur_reply:
        app.query_one("#log", RichLog).write(
            assistant_block(app.cur_reply, _elapsed_seconds(app))
        )
        app.cur_reply = ""
    app.cur_tool = (name, args)
    refresh_streaming_view(app)


def _finish_tool(
    app: MewCodeApp,
    name: str,
    args: str,
    result: str,
    is_error: bool,
) -> None:
    log = app.query_one("#log", RichLog)
    log.write(tool_line(name, args))
    log.write(tool_result_summary(result, is_error))
    app.cur_tool = None
    app.query_one("#streaming", Static).update("")
