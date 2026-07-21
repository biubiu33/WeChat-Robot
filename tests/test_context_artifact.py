from pathlib import Path

import asyncio

from mewcode.context.controller import ContextController
from mewcode.conversation import Conversation
from mewcode.context.artifact import ToolArtifactStore
from mewcode.llm import Message, StreamEvent, ToolResult
from mewcode.session.archive import ArchiveWriter, read_events


def test_artifact_store_spills_large_results(tmp_path: Path) -> None:
    messages = [Message(role="tool", tool_results=[ToolResult("x", "a" * 16_001)])]
    updated, refs = ToolArtifactStore(tmp_path).spill(messages)

    assert len(refs) == 1
    assert (tmp_path / refs[0].relative_path).read_text(
        encoding="utf-8"
    ) == "a" * 16_001
    assert "已归档" in updated[0].tool_results[0].content
    assert messages[0].tool_results[0].content == "a" * 16_001


def test_manual_compact_writes_checkpoint_without_rewriting_archive(
    tmp_path: Path,
) -> None:
    class ProviderStub:
        def redact(self, text: str) -> str:
            return text

        def stream(self, request):
            async def events():
                yield StreamEvent(
                    text="\n".join(
                        f"## {heading}"
                        for heading in (
                            "主要请求和意图",
                            "关键技术概念",
                            "文件和代码段",
                            "错误和修复",
                            "问题解决过程",
                            "所有用户消息",
                            "待办任务",
                            "当前工作",
                            "可能的下一步",
                        )
                    )
                )

            return events()

    path = tmp_path / "session.jsonl"
    writer = ArchiveWriter(path)
    conv = Conversation(
        on_append=lambda message: writer.append_message(message, model="demo")
    )
    for index in range(6):
        conv.add_user(f"消息 {index}: " + "x" * 8_000)
    controller = ContextController(
        ProviderStub(), writer, tmp_path / "cache", 1_000_000
    )

    result = asyncio.run(controller.compact_now(conv, "系统", []))
    writer.close()

    assert result == "已压缩早期上下文"
    assert len(conv.messages()) == 5
    assert [event.type for event in read_events(path)].count("message") == 6
    assert any(event.type == "compact" for event in read_events(path))


def test_request_budget_counts_dynamic_environment_text(tmp_path: Path) -> None:
    class ProviderStub:
        def redact(self, text: str) -> str:
            return text

    writer = ArchiveWriter(tmp_path / "session.jsonl")
    controller = ContextController(
        ProviderStub(), writer, tmp_path / "cache", 1_000_000
    )
    conversation = Conversation()
    conversation.add_user("任务")

    base = controller.request_chars(conversation.messages(), "stable", [], "环境")
    with_skill = controller.request_chars(
        conversation.messages(), "stable", [], "完整 Skill SOP\n\n环境"
    )
    writer.close()

    assert with_skill - base == len("完整 Skill SOP\n\n")
