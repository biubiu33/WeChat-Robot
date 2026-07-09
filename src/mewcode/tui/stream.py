from __future__ import annotations

import time
from typing import TYPE_CHECKING

from textual.widgets import RichLog, Static, TextArea

from .view import assistant_block, error_block, streaming_block

if TYPE_CHECKING:
    from .app import MewCodeApp, SessionState


async def consume_stream(app: MewCodeApp) -> None:
    if app.provider is None:
        return

    try:
        async for event in app.provider.stream(app.conv.messages()):
            if event.err is not None:
                finish_with_error(app, event.err)
                return
            if event.text:
                app.cur_reply += event.text
                refresh_streaming_view(app)
            if event.done:
                finish_with_assistant(app, app.cur_reply)
                return
    except Exception as exc:
        finish_with_error(app, exc)


def tick(app: MewCodeApp, streaming_state: SessionState) -> None:
    if app.state is streaming_state:
        refresh_streaming_view(app)


def refresh_streaming_view(app: MewCodeApp) -> None:
    app.query_one("#streaming", Static).update(
        streaming_block(app.cur_reply, _elapsed_seconds(app))
    )


def finish_with_assistant(app: MewCodeApp, reply: str) -> None:
    elapsed = _elapsed_seconds(app)
    app.query_one("#log", RichLog).write(assistant_block(reply, elapsed))
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
    app.state = app.state.__class__.IDLE
    app.query_one("#streaming", Static).update("")
    input_area = app.query_one("#input", TextArea)
    input_area.read_only = False
    input_area.focus()


def _elapsed_seconds(app: MewCodeApp) -> int:
    return max(0, int(time.monotonic() - app.turn_start))
