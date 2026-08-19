"""请求前归档、压缩和恢复 Prompt Context。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from mewcode.conversation import Conversation
from mewcode.hook import HookEvent
from mewcode.llm import Message, Provider, ToolDefinition
from mewcode.session.archive import ArchiveWriter, CompactCheckpoint
from mewcode.session.repository import RestoredArchive

from .artifact import ToolArtifactStore
from .budget import TokenEstimator
from .compact import summarize


BOUNDARY_NOTICE = "早期历史已压缩。需要文件细节时请重新读取文件，不要根据摘要臆测代码。"
HookDispatcher = Callable[[HookEvent, dict[str, Any]], Awaitable[object]]


class ContextController:
    def __init__(
        self,
        provider: Provider,
        writer: ArchiveWriter,
        cache_dir: Path,
        context_window: int,
        hook_dispatcher: HookDispatcher | None = None,
        *,
        transient_tool_results: bool = False,
    ) -> None:
        self._provider = provider
        self._writer = writer
        self._artifacts = ToolArtifactStore(cache_dir)
        self._context_window = context_window
        self._estimator = TokenEstimator()
        self._summary = ""
        self._failure_count = 0
        self._circuit_open = False
        self._staleness = ""
        self._hook_dispatcher = hook_dispatcher
        self._transient_tool_results = transient_tool_results

    def set_hook_dispatcher(self, dispatcher: HookDispatcher | None) -> None:
        self._hook_dispatcher = dispatcher

    async def prepare_request(
        self,
        conv: Conversation,
        stable: str,
        tools: list[ToolDefinition],
        environment: str = "",
    ) -> list[str]:
        notices: list[str] = []
        messages = conv.messages()
        if self._transient_tool_results and messages and messages[-1].role == "tool":
            return notices
        updated, refs = self._artifacts.spill(messages)
        if refs:
            conv.replace_messages(updated)
            for ref in refs:
                self._writer.append_tool_archive(ref)
            notices.append("已将大型工具结果归档到会话缓存")
        if self._circuit_open:
            return notices
        request_chars = self._request_chars(conv.messages(), stable, tools, environment)
        trigger = self._estimator.compression_trigger(
            request_chars, self._context_window
        )
        if trigger is not None:
            try:
                await self._compact(conv, stable, tools, environment, trigger=trigger)
                notices.append("已压缩早期上下文")
            except Exception:
                self._failure_count += 1
                self._writer.append_compact_failure(self._failure_count)
                if self._failure_count >= 3:
                    self._circuit_open = True
                    notices.append("自动上下文压缩连续失败，已暂停")
        return notices

    async def compact_now(
        self,
        conv: Conversation,
        stable: str,
        tools: list[ToolDefinition],
        environment: str = "",
    ) -> str:
        try:
            changed = await self._compact(
                conv, stable, tools, environment, trigger="manual"
            )
        except Exception as exc:
            return f"上下文压缩失败: {self._provider.redact(str(exc))}"
        return "已压缩早期上下文" if changed else "当前上下文无需压缩"

    def system_context(self) -> str:
        parts = [
            part
            for part in (
                self._summary,
                BOUNDARY_NOTICE if self._summary else "",
                self._staleness,
            )
            if part
        ]
        return "\n\n".join(parts)

    def record_usage(self, input_tokens: int, request_chars: int) -> None:
        self._estimator.record_usage(input_tokens, request_chars)

    def request_chars(
        self,
        messages: list[Message],
        stable: str,
        tools: list[ToolDefinition],
        environment: str = "",
    ) -> int:
        return self._request_chars(messages, stable, tools, environment)

    def restore(self, archive: RestoredArchive) -> list[Message]:
        messages = list(archive.messages)
        for ref in archive.artifact_refs:
            if ref.message_index < len(messages):
                message = messages[ref.message_index]
                if message.role == "tool" and ref.result_index < len(
                    message.tool_results
                ):
                    results = list(message.tool_results)
                    result = results[ref.result_index]
                    results[ref.result_index] = result.__class__(
                        result.tool_call_id,
                        f"工具结果已归档到 .mewcode/cache/{ref.relative_path}。预览：\n{ref.preview}",
                        result.is_error,
                    )
                    messages[ref.message_index] = message.__class__(
                        message.role, message.content, message.tool_calls, results
                    )
        if archive.latest_checkpoint is not None:
            self._summary = archive.latest_checkpoint.summary
            messages = messages[archive.latest_checkpoint.retained_from :]
        self._failure_count = archive.failed_compactions
        self._circuit_open = self._failure_count >= 3
        return messages

    def set_staleness_reminder(self) -> None:
        self._staleness = "本会话已暂停超过七天。部分上下文可能已过时，请重新检查可能变化的工作区状态。"

    async def _compact(
        self,
        conv: Conversation,
        stable: str,
        tools: list[ToolDefinition],
        environment: str,
        *,
        trigger: str,
    ) -> bool:
        messages = conv.messages()
        if len(messages) <= 5:
            return False
        request_chars = self._request_chars(messages, stable, tools, environment)
        if (
            trigger != "manual"
            and self._estimator.compression_trigger(request_chars, self._context_window)
            is None
        ):
            return False
        retained = _retained_start(messages)
        if retained == 0:
            return False
        before_tokens = self._estimator.estimate(request_chars)
        await self._dispatch_hook(HookEvent.PRE_COMPACT, {"trigger": trigger})
        summary = await summarize(self._provider, messages[:retained])
        self._summary = summary
        self._failure_count = 0
        self._circuit_open = False
        conv.replace_messages(messages[retained:])
        self._writer.append_compact(CompactCheckpoint(summary, retained, retained))
        after_tokens = self._estimator.estimate(
            self._request_chars(conv.messages(), stable, tools, environment)
        )
        await self._dispatch_hook(
            HookEvent.POST_COMPACT,
            {
                "trigger": trigger,
                "before_tokens": before_tokens,
                "after_tokens": after_tokens,
            },
        )
        return True

    async def _dispatch_hook(self, event: HookEvent, payload: dict[str, Any]) -> None:
        if self._hook_dispatcher is not None:
            await self._hook_dispatcher(event, payload)

    def _request_chars(
        self,
        messages: list[Message],
        stable: str,
        tools: list[ToolDefinition],
        environment: str,
    ) -> int:
        return (
            len(stable)
            + len(environment)
            + len(self.system_context())
            + sum(
                len(message.content)
                + sum(len(result.content) for result in message.tool_results)
                for message in messages
            )
            + sum(
                len(tool.name) + len(tool.description) + len(str(tool.input_schema))
                for tool in tools
            )
        )


def _retained_start(messages: list[Message]) -> int:
    chars = 0
    index = len(messages)
    while index > 0 and (chars < 40_000 or len(messages) - index < 5):
        index -= 1
        message = messages[index]
        chars += len(message.content) + sum(
            len(result.content) for result in message.tool_results
        )
    return index
