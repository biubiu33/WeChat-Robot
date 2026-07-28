from __future__ import annotations

import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator, Callable
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

import pytest

import mewcode.agent as agent_module
from mewcode.agent import (
    Agent,
    ApprovalRequest,
    MAX_ITERATIONS,
    MAX_UNKNOWN_RUN,
    Mode,
    NOTICE_CANCELLED,
    NOTICE_MAX_ITER,
    NOTICE_UNKNOWN_TOOLS,
    Phase,
)
from mewcode.conversation import Conversation
from mewcode.hook import (
    Action,
    Hook,
    HookCatalog,
    HookContext,
    HookEngine,
    HookEvent,
    HookSessionState,
)
from mewcode.llm import Request, StreamEvent, ToolCall, Usage
from mewcode.permission import Outcome, new_engine
from mewcode.skill import LoadSkillTool, SkillCatalog, SkillRuntime
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


async def collect(agent: Agent, conv: Conversation, mode=Mode.BYPASS, cancel=None):
    cancel_event = cancel if cancel is not None else asyncio.Event()
    return [event async for event in agent.run(conv, mode, cancel_event)]


def hook_context(event: HookEvent, fields: dict[str, object]) -> HookContext:
    return HookContext(
        event,
        {
            "event": event.value,
            "session_id": "test-session",
            "cwd": "test-cwd",
            "mode": "bypassPermissions",
            **fields,
        },
    )


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
                StreamEvent(tool_calls=[ToolCall("slow-id", "slow", "{}")]),
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
    calls = [ToolCall(f"call-{index}", "read_file", "{}") for index in range(1, 5)]
    provider = FakeProvider(
        [[StreamEvent(tool_calls=[call]), StreamEvent(done=True)] for call in calls]
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
    assert all("system-reminder" not in message.content for message in conv.messages())


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


@async_test
async def test_hook_prompt_is_injected_for_current_pre_user_request() -> None:
    provider = FakeProvider([[StreamEvent(text="完成"), StreamEvent(done=True)]])
    state = HookSessionState()
    hooks = HookEngine(
        HookCatalog(
            (
                Hook(
                    "pre-send",
                    HookEvent.PRE_USER_MESSAGE,
                    None,
                    Action("prompt", text="保持 zh-CN"),
                ),
            )
        )
    )
    conv = Conversation()
    conv.add_user("开始")

    await collect(
        Agent(
            provider,
            Registry(),
            hook_engine=hooks,
            hook_state=state,
            hook_context_supplier=hook_context,
        ),
        conv,
    )

    assert provider.requests[0].reminder == "保持 zh-CN"
    assert state.reminders == []
    assert all("保持 zh-CN" not in message.content for message in conv.messages())


@async_test
async def test_hook_blocks_tool_before_permission_and_posts_result() -> None:
    call = ToolCall("blocked", "write_file", '{"path":"blocked.py"}')
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="已调整"), StreamEvent(done=True)],
        ]
    )
    log: list[str] = []
    registry = Registry()
    registry.register(RecordingTool("write_file", log))
    command = (
        f'"{sys.executable}" -c '
        "\"import sys; print('policy denied', file=sys.stderr); raise SystemExit(2)\""
    )
    hooks = HookEngine(
        HookCatalog(
            (
                Hook(
                    "block-write",
                    HookEvent.PRE_TOOL_USE,
                    None,
                    Action("shell", command=command),
                ),
                Hook(
                    "post-result",
                    HookEvent.POST_TOOL_USE,
                    None,
                    Action("prompt", text="工具已被策略拒绝"),
                ),
            )
        )
    )
    conv = Conversation()
    conv.add_user("写文件")

    await collect(
        Agent(
            provider,
            registry,
            hook_engine=hooks,
            hook_state=HookSessionState(),
            hook_context_supplier=hook_context,
        ),
        conv,
    )

    assert log == []
    result = conv.messages()[2].tool_results[0]
    assert result.is_error and "hook_rejected" in result.content
    assert "[hook block-write] policy denied" in result.content
    assert provider.requests[1].reminder == "工具已被策略拒绝"


@async_test
async def test_stop_and_stream_error_hooks_are_dispatched() -> None:
    stop_state = HookSessionState()
    stop_hooks = HookEngine(
        HookCatalog(
            (
                Hook(
                    "on-stop",
                    HookEvent.STOP,
                    None,
                    Action("prompt", text="已自然结束"),
                ),
            )
        )
    )
    successful = FakeProvider([[StreamEvent(text="完成"), StreamEvent(done=True)]])
    conversation = Conversation()
    conversation.add_user("完成任务")

    await collect(
        Agent(
            successful,
            Registry(),
            hook_engine=stop_hooks,
            hook_state=stop_state,
            hook_context_supplier=hook_context,
        ),
        conversation,
    )

    error_state = HookSessionState()
    error_hooks = HookEngine(
        HookCatalog(
            (
                Hook(
                    "on-stream-error",
                    HookEvent.NOTIFICATION,
                    None,
                    Action("prompt", text="请求失败"),
                ),
            )
        )
    )
    failing = FakeProvider([[StreamEvent(err=RuntimeError("network"))]])
    conversation = Conversation()
    conversation.add_user("失败任务")

    await collect(
        Agent(
            failing,
            Registry(),
            hook_engine=error_hooks,
            hook_state=error_state,
            hook_context_supplier=hook_context,
        ),
        conversation,
    )

    assert stop_state.reminders == ["已自然结束"]
    assert error_state.reminders == ["请求失败"]


async def _next_approval(
    agent: Agent, conv: Conversation
) -> tuple[AsyncIterator[object], ApprovalRequest]:
    stream = agent.run(conv, Mode.DEFAULT).__aiter__()
    while True:
        event = await anext(stream)
        if event.approval is not None:
            return stream, event.approval


@async_test
async def test_permission_blacklist_denies_and_agent_loop_continues(
    tmp_path: Path,
) -> None:
    dangerous = ToolCall("danger", "bash", '{"command":"rm -rf /"}')
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[dangerous]), StreamEvent(done=True)],
            [StreamEvent(text="已改用安全方案"), StreamEvent(done=True)],
        ]
    )
    log: list[str] = []
    registry = Registry()
    registry.register(RecordingTool("bash", log))
    engine, err = new_engine(tmp_path)
    conv = Conversation()
    conv.add_user("清理目录")

    assert err is None
    events = await collect(Agent(provider, registry, engine=engine), conv, Mode.BYPASS)

    assert log == []
    assert any(event.tool and event.tool.is_error for event in events)
    result = conv.messages()[2].tool_results[0]
    assert result.tool_call_id == "danger"
    assert result.is_error and "permission_denied" in result.content
    assert conv.messages()[-1].content == "已改用安全方案"


@pytest.mark.parametrize(
    ("outcome", "should_run"),
    [
        (Outcome.ALLOW_ONCE, True),
        (Outcome.ALLOW_SESSION, True),
        (Outcome.ALLOW_FOREVER, True),
        (Outcome.DENY_ONCE, False),
    ],
)
@async_test
async def test_permission_approval_outcomes(
    tmp_path: Path, outcome: Outcome, should_run: bool
) -> None:
    requested = ToolCall("write", "write_file", '{"path":"src/a.py","content":"x"}')
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[requested]), StreamEvent(done=True)],
            [StreamEvent(text="处理完毕"), StreamEvent(done=True)],
        ]
    )
    log: list[str] = []
    registry = Registry()
    registry.register(RecordingTool("write_file", log))
    engine, err = new_engine(tmp_path)
    conv = Conversation()
    conv.add_user("写入文件")

    assert err is None
    stream, approval = await _next_approval(
        Agent(provider, registry, engine=engine), conv
    )
    assert approval.name == "write_file"
    assert "文件写入" in approval.reason
    approval.respond.set_result(outcome)
    events = [event async for event in stream]

    assert bool(log) is should_run
    result = conv.messages()[2].tool_results[0]
    assert result.tool_call_id == "write"
    assert result.is_error is (not should_run)
    assert events[-1].done
    if outcome is Outcome.ALLOW_SESSION:
        followup = ToolCall("again", "write_file", '{"path":"src/a.py","content":"y"}')
        followup_provider = FakeProvider(
            [
                [StreamEvent(tool_calls=[followup]), StreamEvent(done=True)],
                [StreamEvent(text="再次完成"), StreamEvent(done=True)],
            ]
        )
        conv.add_user("再次写入")
        followup_events = await collect(
            Agent(followup_provider, registry, engine=engine), conv, Mode.DEFAULT
        )
        assert not any(event.approval is not None for event in followup_events)
    if outcome is Outcome.ALLOW_FOREVER:
        rebuilt, rebuilt_err = new_engine(tmp_path)
        assert rebuilt_err is None
        assert rebuilt.local.allow


@async_test
async def test_cancel_while_waiting_for_permission_keeps_history_usable(
    tmp_path: Path,
) -> None:
    requested = ToolCall("write", "write_file", '{"path":"a.txt","content":"x"}')
    provider = FakeProvider(
        [[StreamEvent(tool_calls=[requested]), StreamEvent(done=True)]]
    )
    registry = Registry()
    registry.register(RecordingTool("write_file", []))
    engine, err = new_engine(tmp_path)
    conv = Conversation()
    conv.add_user("需要确认")
    cancel = asyncio.Event()
    agent = Agent(provider, registry, engine=engine)
    stream = agent.run(conv, Mode.DEFAULT, cancel).__aiter__()

    assert err is None
    while True:
        event = await anext(stream)
        if event.approval is not None:
            break
    cancel.set()
    events = [event async for event in stream]

    assert any(event.notice == NOTICE_CANCELLED for event in events)
    assert conv.last_role() == "assistant"
    assert conv.messages()[-2].role == "tool"


@async_test
async def test_skill_activation_updates_the_next_request_context_tools_and_model(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user-skills"
    builtin = tmp_path / "builtin-skills"
    entry = user / "review.md"
    entry.parent.mkdir(parents=True)
    entry.write_text(
        "---\n"
        "name: review\n"
        "description: 审查当前改动\n"
        "allowed_tools: [read_file]\n"
        "mode: inline\n"
        "fork_history: none\n"
        "model: skill-model\n"
        "---\n"
        "完整 SOP：{{args}}\n",
        encoding="utf-8",
    )
    runtime = SkillRuntime(
        SkillCatalog.load(project, user, builtin), {"read_file", "write_file"}
    )
    registry = Registry()
    registry.register(RecordingTool("read_file", [], read_only=True))
    registry.register(RecordingTool("write_file", []))
    registry.register(LoadSkillTool(runtime))
    first = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            "load-review",
                            "load_skill",
                            json.dumps({"name": "review", "argument": "API"}),
                        )
                    ]
                ),
                StreamEvent(done=True),
            ]
        ]
    )
    second = FakeProvider([[StreamEvent(text="审查完成"), StreamEvent(done=True)]])
    second.model = "skill-model"
    conv = Conversation()
    conv.add_user("请审查 API")

    agent = Agent(
        first,
        registry,
        prompt_supplier=lambda: ("", "", runtime.available_prompt()),
        environment_supplier=lambda environment: (
            f"{runtime.active_environment()}\n\n{environment}"
            if runtime.active_environment()
            else environment
        ),
        tool_policy_supplier=runtime.ordinary_allowed_tools,
        provider_supplier=lambda: (
            second if runtime.requested_model() == "skill-model" else first
        ),
    )

    events = await collect(agent, conv)

    assert events[-1].done
    assert len(first.requests) == 1
    assert len(second.requests) == 1
    before = first.requests[0]
    after = second.requests[0]
    assert "`review`: 审查当前改动" in before.system.stable
    assert "完整 SOP" not in before.system.stable
    assert after.system.environment.startswith("# 已激活 Skill")
    assert "完整 SOP：API" in after.system.environment
    assert [tool.name for tool in before.tools] == [
        "read_file",
        "write_file",
        "load_skill",
    ]
    assert [tool.name for tool in after.tools] == ["read_file", "load_skill"]


@async_test
async def test_run_to_completion_uses_shared_loop_and_runtime_options() -> None:
    provider = FakeProvider(
        [[StreamEvent(text="completed", usage=Usage(7, 3)), StreamEvent(done=True)]]
    )
    observed = []

    async def observe(usage):
        observed.append(usage)

    result = await Agent(
        provider,
        Registry(),
        max_turns=3,
        stable_system="role instruction",
        reminder_supplier=lambda: "one-shot reminder",
        usage_observer=observe,
    ).run_to_completion(Conversation(), "perform task", Mode.BYPASS)

    assert result.text == "completed"
    assert not result.limit_reached
    assert provider.requests[0].system.stable == "role instruction"
    assert provider.requests[0].reminder == "one-shot reminder"
    assert provider.requests[0].messages[-1].content == "perform task"
    assert observed[0].input == 7


@async_test
async def test_run_to_completion_reports_custom_turn_limit() -> None:
    call = ToolCall("read", "read_file", "{}")
    provider = RepeatingToolProvider(call)
    registry = Registry()
    registry.register(RecordingTool("read_file", [], read_only=True))

    result = await Agent(provider, registry, max_turns=1).run_to_completion(
        Conversation(), "keep reading", Mode.BYPASS
    )

    assert result.limit_reached
    assert "Maximum iterations reached (1)." in result.text
