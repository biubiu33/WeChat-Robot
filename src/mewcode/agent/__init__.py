"""ReAct Agent Loop orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from mewcode import __version__
from mewcode.conversation import Conversation
from mewcode.llm import (
    Provider,
    Request,
    System,
    ToolCall,
    ToolDefinition,
    ToolResult,
    Usage as LlmUsage,
)
from mewcode.prompt import build_system_prompt, gather_environment, plan_reminder
from mewcode.permission import Decision, Engine, Mode, Outcome, new_engine
from mewcode.tool import DEFAULT_TIMEOUT, Registry, Result, error_result

MAX_ITERATIONS = 25
MAX_UNKNOWN_RUN = 3
PLAN_REMINDER_INTERVAL = 4

NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"
EMPTY_RESPONSE_MESSAGE = "模型未返回文本内容。"


class Phase(Enum):
    START = "start"
    END = "end"


@dataclass(frozen=True)
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass(frozen=True)
class ToolEvent:
    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass
class ApprovalRequest:
    name: str
    args: str
    reason: str
    respond: asyncio.Future[Outcome]


@dataclass(frozen=True)
class Event:
    text: str = ""
    tool: ToolEvent | None = None
    usage: Usage | None = None
    iter: int = 0
    notice: str = ""
    done: bool = False
    err: Exception | None = None
    approval: ApprovalRequest | None = None


@dataclass(frozen=True)
class _StreamOutcome:
    text: str
    calls: list[ToolCall]
    usage: LlmUsage | None
    ok: bool
    err: Exception | None = None


class Agent:
    def __init__(
        self,
        provider: Provider,
        registry: Registry,
        version: str = __version__,
        engine: Engine | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._version = version
        self._engine = engine if engine is not None else new_engine(Path.cwd())[0]

    async def run(
        self,
        conv: Conversation,
        mode: Mode = Mode.DEFAULT,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        cancel_event = cancel if cancel is not None else asyncio.Event()
        definitions = self._definitions_for_mode(mode)
        stable_system = build_system_prompt()
        environment = await asyncio.to_thread(
            gather_environment, self._version, self._provider.model
        )
        environment_text = environment.render()
        unknown_run = 0

        for iteration in range(1, MAX_ITERATIONS + 1):
            if cancel_event.is_set():
                self._finish_cancelled(conv)
                yield Event(notice=NOTICE_CANCELLED)
                return
            yield Event(iter=iteration)

            reminder = self._reminder_for(mode, iteration)
            request = Request(
                messages=conv.messages(),
                tools=definitions,
                system=System(stable=stable_system, environment=environment_text),
                reminder=reminder,
            )

            outcome: _StreamOutcome | None = None
            async for item in self._stream_once(request, cancel_event):
                if isinstance(item, Event):
                    yield item
                else:
                    outcome = item

            assert outcome is not None
            if not outcome.ok:
                if cancel_event.is_set():
                    self._finish_cancelled(conv)
                    yield Event(notice=NOTICE_CANCELLED)
                else:
                    self._ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                return

            if outcome.usage is not None:
                yield Event(
                    usage=Usage(
                        input=outcome.usage.input_tokens,
                        output=outcome.usage.output_tokens,
                        cache_write=outcome.usage.cache_write,
                        cache_read=outcome.usage.cache_read,
                    )
                )

            if not outcome.calls:
                final_text = self._ensure_final(outcome.text)
                if not outcome.text.strip():
                    yield Event(text=final_text)
                conv.add_assistant(final_text)
                yield Event(done=True)
                return

            conv.add_assistant_with_tool_calls(outcome.text, outcome.calls)
            unknown_run = unknown_run + 1 if self._all_unknown(outcome.calls) else 0

            execution: _ExecutionOutcome | None = None
            async for item in self._execute_batched(
                outcome.calls,
                cancel_event,
                mode=mode,
                read_only_only=mode is Mode.PLAN,
            ):
                if isinstance(item, Event):
                    yield item
                else:
                    execution = item

            assert execution is not None
            conv.add_tool_results(execution.results)
            if not execution.completed:
                self._finish_cancelled(conv)
                yield Event(notice=NOTICE_CANCELLED)
                return

            if unknown_run >= MAX_UNKNOWN_RUN:
                yield Event(notice=NOTICE_UNKNOWN_TOOLS)
                self._ensure_assistant_tail(conv, NOTICE_UNKNOWN_TOOLS)
                yield Event(done=True)
                return

        yield Event(notice=NOTICE_MAX_ITER)
        self._ensure_assistant_tail(conv, NOTICE_MAX_ITER)
        yield Event(done=True)

    async def _stream_once(
        self,
        request: Request,
        cancel: asyncio.Event,
    ) -> AsyncIterator[Event | _StreamOutcome]:
        text = ""
        calls: list[ToolCall] = []
        usage: LlmUsage | None = None
        stream = self._provider.stream(request)
        iterator = stream.__aiter__()
        next_event: asyncio.Task[object] | None = None
        cancelled: asyncio.Task[bool] | None = None
        try:
            while True:
                if cancel.is_set():
                    yield _StreamOutcome("", [], None, False)
                    return
                next_event = asyncio.create_task(anext(iterator))
                cancelled = asyncio.create_task(cancel.wait())
                done, _ = await asyncio.wait(
                    {next_event, cancelled}, return_when=asyncio.FIRST_COMPLETED
                )
                if cancelled in done:
                    if not next_event.done():
                        next_event.cancel()
                        await asyncio.gather(next_event, return_exceptions=True)
                    yield _StreamOutcome("", [], None, False)
                    return
                try:
                    event = await next_event
                except StopAsyncIteration:
                    break
                if event.err is not None:
                    yield Event(err=event.err)
                    yield _StreamOutcome("", [], None, False, event.err)
                    return
                if event.text:
                    text += event.text
                    yield Event(text=event.text)
                if event.tool_calls:
                    calls.extend(event.tool_calls)
                if event.usage is not None:
                    usage = event.usage
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield Event(err=exc)
            yield _StreamOutcome("", [], None, False, exc)
            return
        finally:
            for task in (next_event, cancelled):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (next_event, cancelled) if task is not None),
                return_exceptions=True,
            )
            aclose = getattr(iterator, "aclose", None)
            if callable(aclose):
                await aclose()
        yield _StreamOutcome(text, calls, usage, True)

    async def _execute_batched(
        self,
        calls: list[ToolCall],
        cancel: asyncio.Event,
        *,
        mode: Mode,
        read_only_only: bool,
    ) -> AsyncIterator[Event | _ExecutionOutcome]:
        results: list[ToolResult | None] = [None] * len(calls)
        index = 0

        while index < len(calls):
            if cancel.is_set():
                self._cancel_remaining(calls, results, index)
                yield _ExecutionOutcome(self._finalize_results(results), False)
                return

            if read_only_only and not self._registry.is_read_only(calls[index].name):
                call = calls[index]
                yield Event(tool=self._tool_start(call))
                result = self._plan_restricted_result(call)
                results[index] = result
                yield Event(tool=self._tool_end(call, result))
                index += 1
                continue

            if self._registry.get(calls[index].name) is None:
                call = calls[index]
                yield Event(tool=self._tool_start(call))
                result = self._permission_denied_result(
                    call, f"未知工具 {call.name}，安全拒绝"
                )
                results[index] = result
                yield Event(tool=self._tool_end(call, result))
                index += 1
                continue

            if self._registry.is_read_only(calls[index].name):
                end = index + 1
                while (
                    end < len(calls)
                    and self._registry.get(calls[end].name) is not None
                    and self._registry.is_read_only(calls[end].name)
                ):
                    end += 1
                for call in calls[index:end]:
                    yield Event(tool=self._tool_start(call))
                allowed: list[int] = []
                for call_index in range(index, end):
                    call = calls[call_index]
                    decision, reason = self._engine.check(mode, call, True)
                    if decision is Decision.ALLOW:
                        allowed.append(call_index)
                    elif decision is Decision.DENY:
                        results[call_index] = self._permission_denied_result(call, reason)
                    else:
                        results[call_index] = self._permission_denied_result(
                            call, "只读工具权限判定异常，安全拒绝"
                        )
                batch = await self._execute_read_batch(calls, results, allowed, cancel)
                for call_index in range(index, end):
                    yield Event(tool=self._tool_end(calls[call_index], results[call_index]))
                if not batch:
                    self._cancel_remaining(calls, results, end)
                    yield _ExecutionOutcome(self._finalize_results(results), False)
                    return
                index = end
                continue

            call = calls[index]
            yield Event(tool=self._tool_start(call))
            decision, reason = self._engine.check(mode, call, False)
            if decision is Decision.ALLOW:
                result, completed = await self._execute_one(call, cancel)
            elif decision is Decision.DENY:
                result, completed = self._permission_denied_result(call, reason), True
            else:
                outcome: Outcome | None = None
                async for item in self._request_approval(call, reason, cancel):
                    if isinstance(item, Event):
                        yield item
                    else:
                        outcome = item
                if outcome is None:
                    result, completed = self._cancelled_result(call), False
                elif outcome is Outcome.DENY_ONCE:
                    result = self._permission_denied_result(call, "用户拒绝本次工具调用")
                    completed = True
                else:
                    if outcome is Outcome.ALLOW_SESSION:
                        self._engine.allow_session(call)
                    elif outcome is Outcome.ALLOW_FOREVER:
                        try:
                            self._engine.persist_local_allow(call)
                        except Exception:
                            pass
                    result, completed = await self._execute_one(call, cancel)
            results[index] = result
            yield Event(tool=self._tool_end(call, result))
            if not completed:
                self._cancel_remaining(calls, results, index + 1)
                yield _ExecutionOutcome(self._finalize_results(results), False)
                return
            index += 1

        yield _ExecutionOutcome(self._finalize_results(results), True)

    async def _execute_read_batch(
        self,
        calls: list[ToolCall],
        results: list[ToolResult | None],
        indexes: list[int],
        cancel: asyncio.Event,
    ) -> bool:
        tasks = [
            asyncio.create_task(self._execute_one(calls[index], cancel))
            for index in indexes
        ]
        completed = True
        try:
            batch_results = await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

        for index, (result, item_completed) in zip(indexes, batch_results, strict=True):
            results[index] = result
            completed = completed and item_completed
        return completed

    async def _request_approval(
        self,
        call: ToolCall,
        reason: str,
        cancel: asyncio.Event,
    ) -> AsyncIterator[Event | Outcome | None]:
        future: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()
        yield Event(
            approval=ApprovalRequest(
                name=call.name,
                args=self._redact(call.input),
                reason=reason,
                respond=future,
            )
        )
        cancelled = asyncio.create_task(cancel.wait())
        try:
            done, _ = await asyncio.wait(
                {future, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancelled in done:
                if not future.done():
                    future.cancel()
                yield None
                return
            yield future.result()
        finally:
            if not cancelled.done():
                cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)

    async def _execute_one(
        self,
        call: ToolCall,
        cancel: asyncio.Event,
    ) -> tuple[ToolResult, bool]:
        if cancel.is_set():
            return self._cancelled_result(call), False

        execution = asyncio.create_task(
            self._registry.execute(call.name, call.input, timeout=DEFAULT_TIMEOUT)
        )
        cancelled = asyncio.create_task(cancel.wait())
        try:
            done, _ = await asyncio.wait(
                {execution, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancelled in done:
                if not execution.done():
                    execution.cancel()
                    await asyncio.gather(execution, return_exceptions=True)
                return self._cancelled_result(call), False
            result = await execution
            return self._to_tool_result(call, result), True
        except asyncio.CancelledError:
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            raise
        finally:
            if not cancelled.done():
                cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)

    def _definitions_for_mode(self, mode: Mode) -> list[ToolDefinition]:
        if mode is Mode.PLAN:
            return self._registry.read_only_definitions()
        return self._registry.definitions()

    def _reminder_for(self, mode: Mode, iteration: int) -> str:
        if mode is not Mode.PLAN:
            return ""
        full = iteration == 1 or (iteration - 1) % PLAN_REMINDER_INTERVAL == 0
        return plan_reminder(full)

    def _all_unknown(self, calls: list[ToolCall]) -> bool:
        return all(self._registry.get(call.name) is None for call in calls)

    def _tool_start(self, call: ToolCall) -> ToolEvent:
        return ToolEvent(
            name=call.name,
            args=self._redact(call.input),
            phase=Phase.START,
        )

    def _tool_end(
        self, call: ToolCall, result: ToolResult | None
    ) -> ToolEvent:
        tool_result = result if result is not None else self._cancelled_result(call)
        return ToolEvent(
            name=call.name,
            args=self._redact(call.input),
            phase=Phase.END,
            result=tool_result.content,
            is_error=tool_result.is_error,
        )

    def _to_tool_result(self, call: ToolCall, result: Result) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            content=self._redact(result.content),
            is_error=result.is_error,
        )

    def _permission_denied_result(self, call: ToolCall, reason: str) -> ToolResult:
        return self._to_tool_result(call, error_result("permission_denied", reason))

    def _cancelled_result(self, call: ToolCall) -> ToolResult:
        return ToolResult(call.id, NOTICE_CANCELLED, is_error=True)

    def _plan_restricted_result(self, call: ToolCall) -> ToolResult:
        result = error_result(
            "plan_mode_restricted",
            f"计划模式只允许只读工具，未执行: {call.name}",
        )
        return self._to_tool_result(call, result)

    def _cancel_remaining(
        self,
        calls: list[ToolCall],
        results: list[ToolResult | None],
        start: int,
    ) -> None:
        for index in range(start, len(calls)):
            if results[index] is None:
                results[index] = self._cancelled_result(calls[index])

    def _finalize_results(
        self, results: list[ToolResult | None]
    ) -> list[ToolResult]:
        return [
            result
            if result is not None
            else ToolResult("", NOTICE_CANCELLED, is_error=True)
            for result in results
        ]

    def _ensure_final(self, text: str) -> str:
        return text if text.strip() else EMPTY_RESPONSE_MESSAGE

    def _ensure_assistant_tail(self, conv: Conversation, fallback: str) -> None:
        if conv.last_role() != "assistant":
            conv.add_assistant(fallback)

    def _finish_cancelled(self, conv: Conversation) -> None:
        self._ensure_assistant_tail(conv, NOTICE_CANCELLED)

    def _redact(self, text: str) -> str:
        redact = getattr(self._provider, "redact", None)
        return redact(text) if callable(redact) else text


@dataclass(frozen=True)
class _ExecutionOutcome:
    results: list[ToolResult]
    completed: bool


__all__ = [
    "Agent",
    "ApprovalRequest",
    "Event",
    "MAX_ITERATIONS",
    "MAX_UNKNOWN_RUN",
    "Mode",
    "NOTICE_CANCELLED",
    "NOTICE_MAX_ITER",
    "NOTICE_STREAM_ERR",
    "NOTICE_UNKNOWN_TOOLS",
    "Phase",
    "PLAN_REMINDER_INTERVAL",
    "ToolEvent",
    "Usage",
]
