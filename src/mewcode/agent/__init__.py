from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum

from mewcode.conversation import Conversation
from mewcode.llm import Provider, ToolCall, ToolResult
from mewcode.tool import DEFAULT_TIMEOUT, Registry

SINGLE_ROUND_LIMIT_MESSAGE = (
    "本轮工具执行已达到单轮上限，新的工具调用未执行。请在下一条消息中继续。"
)
REQUEST_ERROR_HISTORY_MESSAGE = "上一轮模型请求失败，未生成可用答复。"
FOLLOWUP_ERROR_HISTORY_MESSAGE = "工具已执行，但模型续答失败。"
EMPTY_RESPONSE_MESSAGE = "模型未返回文本内容。"


class Phase(Enum):
    START = "start"
    END = "end"


@dataclass(frozen=True)
class ToolEvent:
    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass(frozen=True)
class Event:
    text: str = ""
    tool: ToolEvent | None = None
    done: bool = False
    err: Exception | None = None


class Agent:
    def __init__(self, provider: Provider, registry: Registry) -> None:
        self._provider = provider
        self._registry = registry

    async def run(self, conv: Conversation) -> AsyncIterator[Event]:
        definitions = self._registry.definitions()
        first_text = ""
        calls: list[ToolCall] = []

        try:
            async for event in self._provider.stream(conv.messages(), definitions):
                if event.err is not None:
                    conv.add_assistant(REQUEST_ERROR_HISTORY_MESSAGE)
                    yield Event(err=event.err)
                    return
                if event.text:
                    first_text += event.text
                    yield Event(text=event.text)
                if event.tool_calls:
                    calls.extend(event.tool_calls)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            conv.add_assistant(REQUEST_ERROR_HISTORY_MESSAGE)
            yield Event(err=exc)
            return

        if not calls:
            if not first_text.strip():
                first_text = EMPTY_RESPONSE_MESSAGE
                yield Event(text=first_text)
            conv.add_assistant(first_text)
            yield Event(done=True)
            return

        conv.add_assistant_with_tool_calls(first_text, calls)
        results: list[ToolResult] = []
        for call in calls:
            display_args = self._redact(call.input)
            yield Event(
                tool=ToolEvent(name=call.name, args=display_args, phase=Phase.START)
            )
            result = await self._registry.execute(
                call.name, call.input, timeout=DEFAULT_TIMEOUT
            )
            safe_result = self._redact(result.content)
            yield Event(
                tool=ToolEvent(
                    name=call.name,
                    args=display_args,
                    phase=Phase.END,
                    result=safe_result,
                    is_error=result.is_error,
                )
            )
            results.append(
                ToolResult(
                    tool_call_id=call.id,
                    content=safe_result,
                    is_error=result.is_error,
                )
            )
        conv.add_tool_results(results)

        final_text = ""
        second_calls: list[ToolCall] = []
        try:
            async for event in self._provider.stream(conv.messages(), definitions):
                if event.err is not None:
                    conv.add_assistant(FOLLOWUP_ERROR_HISTORY_MESSAGE)
                    yield Event(err=event.err)
                    return
                if event.text:
                    final_text += event.text
                    yield Event(text=event.text)
                if event.tool_calls:
                    second_calls.extend(event.tool_calls)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            conv.add_assistant(FOLLOWUP_ERROR_HISTORY_MESSAGE)
            yield Event(err=exc)
            return

        if second_calls or not final_text.strip():
            separator = "\n\n" if final_text.strip() else ""
            notice = separator + SINGLE_ROUND_LIMIT_MESSAGE
            final_text += notice
            yield Event(text=notice)
        conv.add_assistant(final_text)
        yield Event(done=True)

    def _redact(self, text: str) -> str:
        redact = getattr(self._provider, "redact", None)
        return redact(text) if callable(redact) else text


__all__ = ["Agent", "Event", "Phase", "ToolEvent"]
