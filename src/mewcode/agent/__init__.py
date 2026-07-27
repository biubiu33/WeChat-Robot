"""ReAct Agent Loop orchestration."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from mewcode import __version__
from mewcode.conversation import Conversation
from mewcode.context import ContextController
from mewcode.hook import (
    HookContext,
    HookDispatch,
    HookEngine,
    HookEvent,
    HookSessionState,
)
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
    natural: bool = False
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
        context: ContextController | None = None,
        prompt_supplier: Callable[[], tuple[str, str] | tuple[str, str, str]]
        | None = None,
        environment_supplier: Callable[[str], str] | None = None,
        tool_policy_supplier: Callable[[], frozenset[str] | None] | None = None,
        provider_supplier: Callable[[], Provider] | None = None,
        hook_engine: HookEngine | None = None,
        hook_state: HookSessionState | None = None,
        hook_context_supplier: Callable[[HookEvent, dict[str, Any]], HookContext]
        | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._version = version
        self._engine = engine if engine is not None else new_engine(Path.cwd())[0]
        self._context = context
        self._prompt_supplier = prompt_supplier
        self._environment_supplier = environment_supplier
        self._tool_policy_supplier = tool_policy_supplier
        self._provider_supplier = provider_supplier
        self._hook_engine = hook_engine
        self._hook_state = hook_state
        self._hook_context_supplier = hook_context_supplier

    async def run(
        self,
        conv: Conversation,
        mode: Mode = Mode.DEFAULT,
        cancel: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        cancel_event = cancel if cancel is not None else asyncio.Event()
        unknown_run = 0

        for iteration in range(1, MAX_ITERATIONS + 1):
            if cancel_event.is_set():
                self._finish_cancelled(conv)
                yield Event(notice=NOTICE_CANCELLED)
                return
            yield Event(iter=iteration)

            provider = self._provider_for_request()
            allowed_tools = (
                self._tool_policy_supplier() if self._tool_policy_supplier else None
            )
            definitions = self._definitions_for_mode(mode, allowed_tools)
            instructions, memory, skills = self._prompt_values()
            stable_system = build_system_prompt(instructions, memory, skills)
            environment = await asyncio.to_thread(
                gather_environment, self._version, provider.model
            )
            environment_text = self._environment_for_request(environment.render())
            reminder = self._reminder_for(mode, iteration)
            if self._context is not None:
                for notice in await self._context.prepare_request(
                    conv, stable_system, definitions, environment_text
                ):
                    yield Event(notice=notice)
            await self._dispatch_hook(
                HookEvent.PRE_USER_MESSAGE,
                {"prompt": self._last_user_prompt(conv)},
            )
            reminder = self._with_hook_reminders(reminder)
            request = Request(
                messages=conv.messages(),
                tools=definitions,
                system=System(
                    stable=stable_system,
                    environment=environment_text,
                    context=self._context.system_context() if self._context else "",
                ),
                reminder=reminder,
            )

            outcome: _StreamOutcome | None = None
            async for item in self._stream_once(provider, request, cancel_event):
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
                    if outcome.err is not None:
                        await self._dispatch_hook(
                            HookEvent.NOTIFICATION,
                            {"kind": "stream_error", "detail": str(outcome.err)},
                        )
                    self._ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                return

            if outcome.usage is not None:
                if self._context is not None:
                    self._context.record_usage(
                        outcome.usage.input_tokens,
                        self._context.request_chars(
                            conv.messages(),
                            stable_system,
                            definitions,
                            environment_text,
                        ),
                    )
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
                await self._dispatch_hook(HookEvent.STOP, {"iter": iteration})
                yield Event(done=True, natural=True)
                return

            conv.add_assistant_with_tool_calls(outcome.text, outcome.calls)
            unknown_run = unknown_run + 1 if self._all_unknown(outcome.calls) else 0

            execution: _ExecutionOutcome | None = None
            async for item in self._execute_batched(
                outcome.calls,
                cancel_event,
                mode=mode,
                read_only_only=mode is Mode.PLAN,
                allowed_tools=allowed_tools,
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
                await self._dispatch_hook(HookEvent.STOP, {"iter": iteration})
                yield Event(done=True)
                return

        yield Event(notice=NOTICE_MAX_ITER)
        self._ensure_assistant_tail(conv, NOTICE_MAX_ITER)
        await self._dispatch_hook(HookEvent.STOP, {"iter": MAX_ITERATIONS})
        yield Event(done=True)

    async def _stream_once(
        self,
        provider: Provider,
        request: Request,
        cancel: asyncio.Event,
    ) -> AsyncIterator[Event | _StreamOutcome]:
        text = ""
        calls: list[ToolCall] = []
        usage: LlmUsage | None = None
        stream = provider.stream(request)
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
        allowed_tools: frozenset[str] | None,
    ) -> AsyncIterator[Event | _ExecutionOutcome]:
        results: list[ToolResult | None] = [None] * len(calls)
        index = 0

        while index < len(calls):
            if cancel.is_set():
                self._cancel_remaining(calls, results, index)
                yield _ExecutionOutcome(self._finalize_results(results), False)
                return

            if not self._tool_is_allowed(calls[index].name, allowed_tools):
                call = calls[index]
                yield Event(tool=self._tool_start(call))
                result = await self._pre_tool_result(call)
                if result is None:
                    result = self._tool_restricted_result(call)
                results[index] = result
                await self._post_tool_hook(call, result)
                yield Event(tool=self._tool_end(call, result))
                index += 1
                continue

            if read_only_only and not self._registry.is_read_only(calls[index].name):
                call = calls[index]
                yield Event(tool=self._tool_start(call))
                result = await self._pre_tool_result(call)
                if result is None:
                    result = self._plan_restricted_result(call)
                results[index] = result
                await self._post_tool_hook(call, result)
                yield Event(tool=self._tool_end(call, result))
                index += 1
                continue

            if self._registry.get(calls[index].name) is None:
                call = calls[index]
                yield Event(tool=self._tool_start(call))
                result = await self._pre_tool_result(call)
                if result is None:
                    result = self._permission_denied_result(
                        call, f"未知工具 {call.name}，安全拒绝"
                    )
                results[index] = result
                await self._post_tool_hook(call, result)
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
                    rejected = await self._pre_tool_result(call)
                    if rejected is not None:
                        results[call_index] = rejected
                        continue
                    decision, reason = self._engine.check(mode, call, True)
                    if decision is Decision.ALLOW:
                        allowed.append(call_index)
                    elif decision is Decision.DENY:
                        results[call_index] = self._permission_denied_result(
                            call, reason
                        )
                    else:
                        results[call_index] = self._permission_denied_result(
                            call, "只读工具权限判定异常，安全拒绝"
                        )
                batch = await self._execute_read_batch(
                    calls, results, allowed, cancel, allowed_tools
                )
                for call_index in range(index, end):
                    result = results[call_index]
                    assert result is not None
                    await self._post_tool_hook(calls[call_index], result)
                    yield Event(tool=self._tool_end(calls[call_index], result))
                if not batch:
                    self._cancel_remaining(calls, results, end)
                    yield _ExecutionOutcome(self._finalize_results(results), False)
                    return
                index = end
                continue

            call = calls[index]
            yield Event(tool=self._tool_start(call))
            rejected = await self._pre_tool_result(call)
            if rejected is not None:
                result, completed = rejected, True
            else:
                decision, reason = self._engine.check(mode, call, False)
                if decision is Decision.ALLOW:
                    result, completed = await self._execute_one(
                        call, cancel, allowed_tools
                    )
                elif decision is Decision.DENY:
                    result, completed = (
                        self._permission_denied_result(call, reason),
                        True,
                    )
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
                        result = self._permission_denied_result(
                            call, "用户拒绝本次工具调用"
                        )
                        completed = True
                    else:
                        if outcome is Outcome.ALLOW_SESSION:
                            self._engine.allow_session(call)
                        elif outcome is Outcome.ALLOW_FOREVER:
                            try:
                                self._engine.persist_local_allow(call)
                            except Exception:
                                pass
                        result, completed = await self._execute_one(
                            call, cancel, allowed_tools
                        )
            results[index] = result
            await self._post_tool_hook(call, result)
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
        allowed_tools: frozenset[str] | None,
    ) -> bool:
        tasks = [
            asyncio.create_task(self._execute_one(calls[index], cancel, allowed_tools))
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
        await self._dispatch_hook(
            HookEvent.NOTIFICATION,
            {"kind": "approval", "detail": call.name},
        )
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
        allowed_tools: frozenset[str] | None,
    ) -> tuple[ToolResult, bool]:
        if cancel.is_set():
            return self._cancelled_result(call), False

        execution = asyncio.create_task(
            self._registry.execute(
                call.name,
                call.input,
                timeout=DEFAULT_TIMEOUT,
                allowed_tools=allowed_tools,
            )
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

    def _definitions_for_mode(
        self, mode: Mode, allowed_tools: frozenset[str] | None
    ) -> list[ToolDefinition]:
        if mode is Mode.PLAN:
            return self._registry.read_only_definitions(allowed_tools)
        return self._registry.definitions(allowed_tools)

    def _prompt_values(self) -> tuple[str, str, str]:
        if self._prompt_supplier is None:
            return "", "", ""
        values = self._prompt_supplier()
        if len(values) == 2:
            instructions, memory = values
            return instructions, memory, ""
        instructions, memory, skills = values
        return instructions, memory, skills

    def _environment_for_request(self, environment: str) -> str:
        if self._environment_supplier is None:
            return environment
        return self._environment_supplier(environment)

    def _provider_for_request(self) -> Provider:
        return self._provider_supplier() if self._provider_supplier else self._provider

    def _reminder_for(self, mode: Mode, iteration: int) -> str:
        if mode is not Mode.PLAN:
            return ""
        full = iteration == 1 or (iteration - 1) % PLAN_REMINDER_INTERVAL == 0
        return plan_reminder(full)

    def _with_hook_reminders(self, reminder: str) -> str:
        if self._hook_engine is None or self._hook_state is None:
            return reminder
        prompts = self._hook_engine.take_reminders(self._hook_state)
        return "\n".join(item for item in (reminder, *prompts) if item)

    async def _dispatch_hook(
        self, event: HookEvent, payload: dict[str, Any]
    ) -> HookDispatch:
        if self._hook_engine is None or self._hook_state is None:
            return HookDispatch()
        context = (
            self._hook_context_supplier(event, payload)
            if self._hook_context_supplier is not None
            else HookContext(event, {"event": event.value, **payload})
        )
        return await self._hook_engine.dispatch(event, context, self._hook_state)

    async def _pre_tool_result(self, call: ToolCall) -> ToolResult | None:
        dispatch = await self._dispatch_hook(
            HookEvent.PRE_TOOL_USE,
            {"tool_name": call.name, "tool_input": self._tool_input(call)},
        )
        if not dispatch.blocked:
            return None
        reason = f"[hook {dispatch.blocked_by}] {dispatch.reason}"
        return self._to_tool_result(call, error_result("hook_rejected", reason))

    async def _post_tool_hook(self, call: ToolCall, result: ToolResult) -> None:
        await self._dispatch_hook(
            HookEvent.POST_TOOL_USE,
            {
                "tool_name": call.name,
                "tool_input": self._tool_input(call),
                "tool_result": result.content,
                "is_error": result.is_error,
            },
        )

    @staticmethod
    def _tool_input(call: ToolCall) -> dict[str, Any]:
        try:
            value = json.loads(call.input or "{}")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _last_user_prompt(conv: Conversation) -> str:
        for message in reversed(conv.messages()):
            if message.role == "user":
                return message.content
        return ""

    def _all_unknown(self, calls: list[ToolCall]) -> bool:
        return all(self._registry.get(call.name) is None for call in calls)

    def _tool_start(self, call: ToolCall) -> ToolEvent:
        return ToolEvent(
            name=call.name,
            args=self._redact(call.input),
            phase=Phase.START,
        )

    def _tool_end(self, call: ToolCall, result: ToolResult | None) -> ToolEvent:
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

    def _tool_restricted_result(self, call: ToolCall) -> ToolResult:
        result = error_result("tool_not_allowed", f"当前 Skill 不允许工具: {call.name}")
        return self._to_tool_result(call, result)

    def _tool_is_allowed(self, name: str, allowed_tools: frozenset[str] | None) -> bool:
        return (
            allowed_tools is None
            or name in allowed_tools
            or self._registry.is_system(name)
        )

    def _cancel_remaining(
        self,
        calls: list[ToolCall],
        results: list[ToolResult | None],
        start: int,
    ) -> None:
        for index in range(start, len(calls)):
            if results[index] is None:
                results[index] = self._cancelled_result(calls[index])

    def _finalize_results(self, results: list[ToolResult | None]) -> list[ToolResult]:
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
