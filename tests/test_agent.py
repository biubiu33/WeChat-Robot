from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import pytest

from mewcode.agent import Agent, Phase
from mewcode.conversation import Conversation
from mewcode.llm import Message, StreamEvent, ToolCall, ToolDefinition
from mewcode.tool import Registry, Result

F = TypeVar("F", bound=Callable[..., Any])


def async_test(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(func(*args, **kwargs))

    return wrapper  # type: ignore[return-value]


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[list[StreamEvent]]) -> None:
        self.responses = responses
        self.requests: list[tuple[list[Message], list[ToolDefinition]]] = []

    def redact(self, text: str) -> str:
        return text.replace("secret-key", "***")

    async def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        self.requests.append((list(msgs), list(tools)))
        for event in self.responses[len(self.requests) - 1]:
            yield event


class RecordingTool:
    def __init__(self, name: str, log: list[str], *, fail: bool = False) -> None:
        self._name = name
        self._log = log
        self._fail = fail

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return f"执行 {self._name}"

    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        self._log.append(self._name)
        return Result(f"{self._name}:{args}", is_error=self._fail)


async def collect(agent: Agent, conv: Conversation):
    return [event async for event in agent.run(conv)]


@async_test
async def test_plain_text_turn_uses_one_request() -> None:
    provider = FakeProvider(
        [[StreamEvent(text="你"), StreamEvent(text="好"), StreamEvent(done=True)]]
    )
    conv = Conversation()
    conv.add_user("你好")

    events = await collect(Agent(provider, Registry()), conv)

    assert len(provider.requests) == 1
    assert "".join(event.text for event in events) == "你好"
    assert events[-1].done
    assert conv.messages()[-1].content == "你好"


@async_test
async def test_empty_plain_response_gets_non_empty_history_message() -> None:
    provider = FakeProvider([[StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("你好")

    events = await collect(Agent(provider, Registry()), conv)

    assert "未返回文本" in conv.messages()[-1].content
    assert "未返回文本" in "".join(event.text for event in events)


@async_test
async def test_multiple_tools_run_in_order_and_results_are_fed_back() -> None:
    calls = [
        ToolCall("1", "first", '{"x":1}'),
        ToolCall("2", "second", '{"x":2}'),
    ]
    provider = FakeProvider(
        [
            [StreamEvent(text="先检查"), StreamEvent(tool_calls=calls), StreamEvent(done=True)],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    log: list[str] = []
    registry = Registry()
    registry.register(RecordingTool("first", log, fail=True))
    registry.register(RecordingTool("second", log))
    conv = Conversation()
    conv.add_user("执行")

    events = await collect(Agent(provider, registry), conv)

    assert log == ["first", "second"]
    assert len(provider.requests) == 2
    second_history = provider.requests[1][0]
    assert [message.role for message in second_history] == ["user", "assistant", "tool"]
    assert second_history[-1].tool_results[0].is_error is True
    assert second_history[-1].tool_results[1].is_error is False
    phases = [event.tool.phase for event in events if event.tool]
    assert phases == [Phase.START, Phase.END, Phase.START, Phase.END]
    assert conv.messages()[-1].content == "完成"


@async_test
async def test_second_tool_request_is_not_executed() -> None:
    provider = FakeProvider(
        [
            [
                StreamEvent(tool_calls=[ToolCall("1", "first", "{}")]),
                StreamEvent(done=True),
            ],
            [
                StreamEvent(text="还需要继续"),
                StreamEvent(tool_calls=[ToolCall("2", "second", "{}")]),
                StreamEvent(done=True),
            ],
        ]
    )
    log: list[str] = []
    registry = Registry()
    registry.register(RecordingTool("first", log))
    registry.register(RecordingTool("second", log))
    conv = Conversation()
    conv.add_user("两步任务")

    events = await collect(Agent(provider, registry), conv)

    assert log == ["first"]
    assert len(provider.requests) == 2
    assert "单轮上限" in conv.messages()[-1].content
    assert "单轮上限" in "".join(event.text for event in events)


@async_test
async def test_tool_results_and_display_arguments_redact_api_key() -> None:
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall("1", "leaky", '{"command":"echo secret-key"}')
                    ]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    log: list[str] = []
    registry = Registry()
    registry.register(RecordingTool("leaky", log))
    conv = Conversation()
    conv.add_user("测试脱敏")

    events = await collect(Agent(provider, registry), conv)

    tool_events = [event.tool for event in events if event.tool]
    assert all("secret-key" not in event.args for event in tool_events)
    assert "secret-key" not in conv.messages()[2].tool_results[0].content
    assert "***" in conv.messages()[2].tool_results[0].content


@async_test
async def test_provider_error_stops_turn_without_assistant_message() -> None:
    provider = FakeProvider([[StreamEvent(err=RuntimeError("bad key"))]])
    conv = Conversation()
    conv.add_user("测试")

    events = await collect(Agent(provider, Registry()), conv)

    assert isinstance(events[-1].err, RuntimeError)
    assert [message.role for message in conv.messages()] == ["user", "assistant"]
    assert "请求失败" in conv.messages()[-1].content


@async_test
async def test_agent_propagates_cancellation() -> None:
    class BlockingProvider(FakeProvider):
        async def stream(self, msgs, tools):
            await asyncio.sleep(10)
            yield StreamEvent(done=True)

    conv = Conversation()
    conv.add_user("等待")
    task = asyncio.create_task(collect(Agent(BlockingProvider([]), Registry()), conv))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
