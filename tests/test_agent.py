from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from functools import wraps
from typing import Any, TypeVar

import pytest

import mewcode.agent as agent_module
from mewcode.agent import (
    Agent,
    MAX_ITERATIONS,
    MAX_UNKNOWN_RUN,
    Mode,
    NOTICE_CANCELLED,
    NOTICE_MAX_ITER,
    NOTICE_UNKNOWN_TOOLS,
    Phase,
)
from mewcode.conversation import Conversation
from mewcode.llm import Request, StreamEvent, ToolCall, ToolDefinition, Usage
from mewcode.tool import Registry, Result, new_default_registry

F = TypeVar("F", bound=Callable[..., Any])


def async_test(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(func(*args, **kwargs))

    return wrapper  # type: ignore[return-value]


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.requests: list[Request] = []

    def redact(self, text: str) -> str:
        return text.replace("secret-key", "***")

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(
            Request(
                messages=list(req.messages),
                tools=list(req.tools),
                system=req.system,
                reminder=req.reminder,
            )
        )
        index = len(self.requests) - 1
        for event in self.scripts[index]:
            yield event


class RepeatingToolProvider(FakeProvider):
    def __init__(self, call: ToolCall) -> None:
        super().__init__([])
        self.call = call

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        yield StreamEvent(tool_calls=[self.call], usage=Usage(3, 2))
        yield StreamEvent(done=True)


class RecordingTool:
    def __init__(
        self,
        name: str,
        log: list[str],
        *,
        read_only: bool = False,
        delay: float = 0.0,
        started: asyncio.Event | None = None,
    ) -> None:
        self._name = name
        self._log = log
        self.read_only = read_only
        self._delay = delay
        self._started = started
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.running = 0
        self.max_running = 0

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return f"执行 {self._name}"

    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        self.started_at = time.monotonic()
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        self._log.append(f"start:{self._name}")
        if self._started is not None:
            self._started.set()
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
            return Result(f"{self._name}:{args}")
        finally:
            self.running -= 1
            self.finished_at = time.monotonic()
            self._log.append(f"end:{self._name}")


async def collect(agent: Agent, conv: Conversation, mode=Mode.NORMAL, cancel=None):
    cancel_event = cancel if cancel is not None else asyncio.Event()
    return [event async for event in agent.run(conv, mode, cancel_event)]


@async_test
async def test_react_loop_runs_multiple_rounds_and_reports_events() -> None:
    call = ToolCall("call-1", "read_file", '{"path":"a.py"}')
    provider = FakeProvider(
        [
            [
                StreamEvent(text="先读取。"),
                StreamEvent(tool_calls=[call]),
                StreamEvent(usage=Usage(10, 4, cache_write=6, cache_read=2)),
                StreamEvent(done=True),
            ],
            [
                StreamEvent(text="读取完成。"),
                StreamEvent(usage=Usage(20, 3)),
                StreamEvent(done=True),
            ],
        ]
    )
    log: list[str] = []
    registry = Registry()
    registry.register(RecordingTool("read_file", log, read_only=True))
    conv = Conversation()
    conv.add_user("读取文件并总结")

    events = await collect(Agent(provider, registry), conv)

    assert len(provider.requests) == 2
    assert [event.iter for event in events if event.iter] == [1, 2]
    assert [event.usage for event in events if event.usage] == [
        agent_module.Usage(10, 4, 6, 2),
        agent_module.Usage(20, 3),
    ]
    assert [event.tool.phase for event in events if event.tool] == [
        Phase.START,
        Phase.END,
    ]
    assert events[-1].done
    assert [message.role for message in conv.messages()] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert conv.messages()[-1].content == "读取完成。"
    assert log == ["start:read_file", "end:read_file"]


@async_test
async def test_iteration_limit_stops_after_maximum_rounds() -> None:
    provider = RepeatingToolProvider(ToolCall("id", "known", "{}"))
    registry = Registry()
    registry.register(RecordingTool("known", [], read_only=True))
    conv = Conversation()
    conv.add_user("不要停")

    events = await collect(Agent(provider, registry), conv)

    assert len(provider.requests) == MAX_ITERATIONS
    assert any(event.notice == NOTICE_MAX_ITER for event in events)
    assert events[-1].done
    assert conv.last_role() == "assistant"
    assert conv.messages()[-1].content == NOTICE_MAX_ITER


@async_test
async def test_consecutive_unknown_tools_stop_and_known_tool_resets_counter() -> None:
    unknown = ToolCall("unknown", "not_registered", "{}")
    known = ToolCall("known", "read_file", "{}")
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[unknown]), StreamEvent(done=True)],
            [StreamEvent(tool_calls=[unknown]), StreamEvent(done=True)],
            [StreamEvent(tool_calls=[known]), StreamEvent(done=True)],
            [StreamEvent(tool_calls=[unknown]), StreamEvent(done=True)],
            [StreamEvent(tool_calls=[unknown]), StreamEvent(done=True)],
            [StreamEvent(tool_calls=[unknown]), StreamEvent(done=True)],
        ]
    )
    registry = Registry()
    registry.register(RecordingTool("read_file", [], read_only=True))
    conv = Conversation()
    conv.add_user("继续")

    events = await collect(Agent(provider, registry), conv)

    assert len(provider.requests) == 6
    assert any(event.notice == NOTICE_UNKNOWN_TOOLS for event in events)
    assert conv.last_role() == "assistant"


@async_test
async def test_only_unknown_tools_stop_at_threshold() -> None:
    provider = RepeatingToolProvider(ToolCall("id", "missing", "{}"))
    conv = Conversation()
    conv.add_user("幻觉工具")

    events = await collect(Agent(provider, Registry()), conv)

    assert len(provider.requests) == MAX_UNKNOWN_RUN
    assert any(event.notice == NOTICE_UNKNOWN_TOOLS for event in events)
    assert conv.last_role() == "assistant"


@async_test
async def test_read_only_batch_runs_concurrently_and_effectful_tool_follows() -> None:
    calls = [
        ToolCall("1", "read_a", "{}"),
        ToolCall("2", "read_b", "{}"),
        ToolCall("3", "write", "{}"),
    ]
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=calls), StreamEvent(done=True)],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    log: list[str] = []
    first = RecordingTool("read_a", log, read_only=True, delay=0.05)
    second = RecordingTool("read_b", log, read_only=True, delay=0.05)
    write = RecordingTool("write", log, read_only=False)
    registry = Registry()
    registry.register(first)
    registry.register(second)
    registry.register(write)
    conv = Conversation()
    conv.add_user("并发读取后写入")

    events = await collect(Agent(provider, registry), conv)

    assert first.started_at is not None and second.started_at is not None
    assert first.finished_at is not None and second.finished_at is not None
    assert write.started_at is not None
    assert abs(first.started_at - second.started_at) < 0.03
    assert write.started_at >= max(first.finished_at, second.finished_at)
    assert [event.tool.name for event in events if event.tool] == [
        "read_a",
        "read_b",
        "read_a",
        "read_b",
        "write",
        "write",
    ]
    tool_results = conv.messages()[2].tool_results
    assert [result.tool_call_id for result in tool_results] == ["1", "2", "3"]


@async_test
async def test_cancel_records_cancelled_results_and_allows_followup() -> None:
    started = asyncio.Event()
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall("slow-id", "slow", "{}")]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="后续正常"), StreamEvent(done=True)],
        ]
    )
    registry = Registry()
    registry.register(
        RecordingTool("slow", [], delay=5, started=started, read_only=False)
    )
    conv = Conversation()
    conv.add_user("开始慢任务")
    cancel = asyncio.Event()
    task = asyncio.create_task(collect(Agent(provider, registry), conv, cancel=cancel))
    await started.wait()
    cancel.set()
    events = await task

    assert not any(event.done for event in events)
    assert conv.last_role() == "assistant"
    assert conv.messages()[-2].role == "tool"
    assert conv.messages()[-2].tool_results[0].content == NOTICE_CANCELLED
    assert conv.messages()[-1].content == NOTICE_CANCELLED

    conv.add_user("还能继续吗")
    followup = await collect(Agent(provider, registry), conv)
    assert followup[-1].done
    assert conv.messages()[-1].content == "后续正常"


@async_test
async def test_plan_mode_sends_read_only_tools_and_dynamic_reminder() -> None:
    provider = FakeProvider([[StreamEvent(text="计划如下"), StreamEvent(done=True)]])
    conv = Conversation()
    conv.add_user("制定计划")

    events = await collect(
        Agent(provider, new_default_registry()), conv, mode=Mode.PLAN
    )

    assert events[-1].done
    request = provider.requests[0]
    assert [definition.name for definition in request.tools] == [
        "read_file",
        "glob",
        "grep",
    ]
    assert request.system.stable
    assert "环境信息" in request.system.environment
    assert request.reminder.startswith("<system-reminder>")
    assert "read_file、glob、grep" in request.reminder


@async_test
async def test_plan_reminder_frequency_and_history_are_isolated() -> None:
    calls = [
        ToolCall(f"call-{index}", "read_file", "{}") for index in range(1, 5)
    ]
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)]
            for call in calls
        ]
        + [[StreamEvent(text="计划完成"), StreamEvent(done=True)]]
    )
    registry = Registry()
    registry.register(RecordingTool("read_file", [], read_only=True))
    conv = Conversation()
    conv.add_user("请调研并制定计划")

    events = await collect(Agent(provider, registry), conv, mode=Mode.PLAN)

    assert events[-1].done
    assert len(provider.requests) == 5
    assert "read_file、glob、grep" in provider.requests[0].reminder
    assert "read_file、glob、grep" not in provider.requests[1].reminder
    assert "read_file、glob、grep" not in provider.requests[3].reminder
    assert "read_file、glob、grep" in provider.requests[4].reminder
    assert provider.requests[0].system.stable == provider.requests[4].system.stable
    assert all(
        "system-reminder" not in message.content for message in conv.messages()
    )


@async_test
async def test_plan_mode_never_executes_hallucinated_side_effect_tool() -> None:
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall("write", "write_file", '{"path":"a.txt"}')]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="计划完成"), StreamEvent(done=True)],
        ]
    )
    log: list[str] = []
    registry = Registry()
    registry.register(RecordingTool("write_file", log, read_only=False))
    conv = Conversation()
    conv.add_user("只制定计划")

    events = await collect(Agent(provider, registry), conv, mode=Mode.PLAN)

    assert log == []
    assert conv.messages()[2].tool_results[0].is_error is True
    assert "plan_mode_restricted" in conv.messages()[2].tool_results[0].content
    assert events[-1].done


@async_test
async def test_stream_error_stops_and_preserves_assistant_tail() -> None:
    provider = FakeProvider([[StreamEvent(err=RuntimeError("network"))]])
    conv = Conversation()
    conv.add_user("出错")

    events = await collect(Agent(provider, Registry()), conv)

    assert isinstance(next(event.err for event in events if event.err), RuntimeError)
    assert conv.last_role() == "assistant"
    assert "请求出错" in conv.messages()[-1].content
