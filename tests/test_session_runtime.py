from __future__ import annotations

from pathlib import Path

from mewcode.llm import Message
from mewcode.session.archive import read_events
from mewcode.session.runtime import SessionRuntime


class FakeProvider:
    name = "fake"
    model = "fake-model"


def test_archive_transform_can_skip_message(tmp_path: Path) -> None:
    runtime = SessionRuntime.new(
        tmp_path,
        FakeProvider(),
        10_000,
        enable_title=False,
        archive_message_transform=(
            lambda message: None if message.role == "assistant" else message
        ),
    )
    runtime.conversation.add_user("用户消息")
    runtime.conversation.add_assistant("暂缓消息")
    runtime.conversation.add_tool_results([])
    path = runtime.paths.archive_path
    runtime.close()

    messages = [event.data for event in read_events(path) if event.type == "message"]
    assert [message["role"] for message in messages] == ["user", "tool"]
    assert all(message["content"] != "暂缓消息" for message in messages)


def test_archive_transform_keeps_normal_messages(tmp_path: Path) -> None:
    runtime = SessionRuntime.new(
        tmp_path,
        FakeProvider(),
        10_000,
        enable_title=False,
        archive_message_transform=lambda message: Message(
            message.role, message.content
        ),
    )
    runtime.conversation.add_user("保留")
    path = runtime.paths.archive_path
    runtime.close()

    messages = [event.data for event in read_events(path) if event.type == "message"]
    assert [message["content"] for message in messages] == ["保留"]
