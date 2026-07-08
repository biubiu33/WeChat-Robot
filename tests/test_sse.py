from __future__ import annotations

from mewcode.sse import SSEEvent, iter_sse_events


def test_parses_data_without_event() -> None:
    events = list(iter_sse_events(["data: hello\n", "\n"]))

    assert events == [SSEEvent(event=None, data="hello")]


def test_parses_event_and_multiline_data() -> None:
    events = list(
        iter_sse_events(
            [
                "event: message\n",
                "data: 第一行\n",
                "data: 第二行\n",
                "\n",
            ]
        )
    )

    assert events == [SSEEvent(event="message", data="第一行\n第二行")]


def test_ignores_comments_and_blank_events() -> None:
    events = list(
        iter_sse_events(
            [
                ": keep alive\n",
                "\n",
                "data: 正文\n",
                "\n",
            ]
        )
    )

    assert events == [SSEEvent(event=None, data="正文")]


def test_flushes_final_event_without_trailing_blank_line() -> None:
    events = list(iter_sse_events(["event: done\n", "data: 完成\n"]))

    assert events == [SSEEvent(event="done", data="完成")]
