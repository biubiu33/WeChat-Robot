from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from functools import wraps
from typing import Any, TypeVar

from mewcode.config import ProviderConfig
from mewcode.llm import Message, StreamEvent, ToolDefinition
from mewcode.tool import new_default_registry
from mewcode.tui.app import MewCodeApp, SessionState
from mewcode.tui.view import tool_line, tool_result_summary

F = TypeVar("F", bound=Callable[..., Any])


def async_test(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(func(*args, **kwargs))

    return wrapper  # type: ignore[return-value]


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.requests = 0

    async def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        self.requests += 1
        assert len(tools) == 6
        yield StreamEvent(text=f"回复 {self.requests}")
        yield StreamEvent(done=True)


async def _wait_until_idle(app: MewCodeApp) -> None:
    for _ in range(200):
        if app.state is SessionState.IDLE and app._stream_task is None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("TUI 回合未在预期时间内结束")


@async_test
async def test_tui_passes_tools_and_restores_input_for_multiple_turns() -> None:
    config = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="test-key",
        model="fake-model",
    )
    app = MewCodeApp([config], registry=new_default_registry())
    provider = FakeProvider()

    async with app.run_test():
        app.provider = provider
        input_area = app.query_one("#input")

        for question in ("第一问", "第二问"):
            input_area.text = question
            await app.submit_current_input()
            await _wait_until_idle(app)
            assert input_area.read_only is False
            assert input_area.has_focus

    assert provider.requests == 2
    assert [message.role for message in app.conv.messages()] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_tool_line_only_previews_safe_key_argument() -> None:
    rendered = tool_line(
        "write_file",
        '{"path":"a.py","content":"secret file content"}',
    )

    assert rendered.plain == "● write_file(a.py)"
    assert "secret file content" not in rendered.plain


def test_tool_result_summary_limits_visible_lines() -> None:
    rendered = tool_result_summary("\n".join(f"line {i}" for i in range(20)), False)

    assert "line 7" in rendered.plain
    assert "line 8" not in rendered.plain
    assert "[truncated]" in rendered.plain
