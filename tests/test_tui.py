from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from functools import wraps
from io import StringIO
from typing import Any, TypeVar

from rich.console import Console
from mewcode.config import ProviderConfig
from mewcode.agent import Mode
from mewcode.llm import Message, StreamEvent, ToolDefinition, Usage
from mewcode.tool import new_default_registry
from mewcode.tui.app import MewCodeApp, SessionState
from mewcode.tui.view import status_bar, tool_line, tool_result_summary

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
        system_suffix: str = "",
    ) -> AsyncIterator[StreamEvent]:
        self.requests += 1
        assert len(tools) == 6
        yield StreamEvent(text=f"回复 {self.requests}")
        yield StreamEvent(usage=Usage(10, 5))
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
    assert app.usage_in == 20
    assert app.usage_out == 10
    assert [message.role for message in app.conv.messages()] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


@async_test
async def test_tui_plan_and_do_switch_mode_and_use_directive() -> None:
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
        input_area.text = "/plan"
        await app.submit_current_input()
        assert app.mode is Mode.PLAN
        assert app.state is SessionState.IDLE

        input_area.text = "/do"
        await app.submit_current_input()
        await _wait_until_idle(app)

    assert app.mode is Mode.NORMAL
    assert provider.requests == 1
    assert app.conv.messages()[0].content == "请按上面的计划开始执行。"


@async_test
async def test_tui_escape_cancels_streaming_turn_without_exiting() -> None:
    class BlockingProvider(FakeProvider):
        async def stream(self, msgs, tools, system_suffix=""):
            self.requests += 1
            await asyncio.sleep(5)
            yield StreamEvent(text="不应出现")
            yield StreamEvent(done=True)

    config = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="test-key",
        model="fake-model",
    )
    app = MewCodeApp([config], registry=new_default_registry())
    provider = BlockingProvider()

    async with app.run_test():
        app.provider = provider
        input_area = app.query_one("#input")
        input_area.text = "开始"
        await app.submit_current_input()
        await asyncio.sleep(0)
        app.action_cancel_turn()
        await _wait_until_idle(app)

        assert input_area.read_only is False
        assert input_area.has_focus
        assert app.conv.last_role() == "assistant"


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


def test_status_bar_shows_plan_mode_and_compact_usage() -> None:
    rendered = status_bar("fake", "model", Mode.PLAN, 1200, 9)
    output = StringIO()
    Console(file=output, force_terminal=False).print(rendered)

    text = output.getvalue()
    assert "PLAN" in text
    assert "1.2k" in text
    assert "↑" in text and "↓" in text
