"""请求前归档、压缩和恢复 Prompt Context。"""

from __future__ import annotations

from pathlib import Path

from mewcode.conversation import Conversation
from mewcode.llm import Message, Provider, ToolDefinition
from mewcode.session.archive import ArchiveWriter, CompactCheckpoint
from mewcode.session.repository import RestoredArchive

from .artifact import ToolArtifactStore
from .budget import TokenEstimator
from .compact import summarize


BOUNDARY_NOTICE = "早期历史已压缩。需要文件细节时请重新读取文件，不要根据摘要臆测代码。"


class ContextController:
    def __init__(
        self,
        provider: Provider,
        writer: ArchiveWriter,
        cache_dir: Path,
        context_window: int,
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

    async def prepare_request(
        self, conv: Conversation, stable: str, tools: list[ToolDefinition]
    ) -> list[str]:
        notices: list[str] = []
        updated, refs = self._artifacts.spill(conv.messages())
        if refs:
            conv.replace_messages(updated)
            for ref in refs:
                self._writer.append_tool_archive(ref)
            notices.append("已将大型工具结果归档到会话缓存")
        if self._circuit_open:
            return notices
        if self._estimator.exceeds(
            self._request_chars(conv.messages(), stable, tools), self._context_window
        ):
            try:
                await self._compact(conv, stable, tools, manual=False)
                notices.append("已压缩早期上下文")
            except Exception:
                self._failure_count += 1
                self._writer.append_compact_failure(self._failure_count)
                if self._failure_count >= 3:
                    self._circuit_open = True
                    notices.append("自动上下文压缩连续失败，已暂停")
        return notices

    async def compact_now(
        self, conv: Conversation, stable: str, tools: list[ToolDefinition]
    ) -> str:
        try:
            changed = await self._compact(conv, stable, tools, manual=True)
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
        self, messages: list[Message], stable: str, tools: list[ToolDefinition]
    ) -> int:
        return self._request_chars(messages, stable, tools)

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
        *,
        manual: bool,
    ) -> bool:
        messages = conv.messages()
        if len(messages) <= 5:
            return False
        if not manual and not self._estimator.exceeds(
            self._request_chars(messages, stable, tools), self._context_window
        ):
            return False
        retained = _retained_start(messages)
        if retained == 0:
            return False
        summary = await summarize(self._provider, messages[:retained])
        self._summary = summary
        self._failure_count = 0
        self._circuit_open = False
        conv.replace_messages(messages[retained:])
        self._writer.append_compact(CompactCheckpoint(summary, retained, retained))
        return True

    def _request_chars(
        self, messages: list[Message], stable: str, tools: list[ToolDefinition]
    ) -> int:
        return (
            len(stable)
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
