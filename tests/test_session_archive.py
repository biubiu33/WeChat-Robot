from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from mewcode.llm import Message, ToolCall, ToolResult
from mewcode.session.archive import (
    ArchiveWriter,
    ArtifactRef,
    CompactCheckpoint,
    message_from_data,
    read_events,
)
from mewcode.session.paths import SESSION_ID_RE, create_session, ensure_project_layout


def test_session_paths_create_id_cache_and_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    paths = create_session(tmp_path, datetime(2026, 7, 17, 12, 34, 56))

    assert SESSION_ID_RE.fullmatch(paths.session_id)
    assert paths.archive_path.exists()
    assert paths.cache_dir.is_dir()
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == (
        ".venv/\n.mewcode/sessions/\n.mewcode/cache/\n.mewcode/memory/\n"
        ".mewcode/wechat.sqlite3*\n"
    )

    ensure_project_layout(tmp_path)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8").count(
        ".mewcode/cache/"
    ) == 1


def test_writer_serializes_messages_metadata_and_context_events(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    writer = ArchiveWriter(path)
    writer.append_message(Message(role="user", content="你好"), model="demo-model")
    writer.append_message(
        Message(
            role="assistant",
            content="读取文件",
            tool_calls=[ToolCall("call-1", "read_file", '{"path":"a.py"}')],
        )
    )
    writer.append_message(
        Message(role="tool", tool_results=[ToolResult("call-1", "print('ok')")])
    )
    writer.append_title("读取项目文件")
    writer.append_tool_archive(ArtifactRef(2, 0, "cache/out.txt", "print", 12))
    writer.append_compact(CompactCheckpoint("正式摘要", 2, 2))
    writer.append_compact_failure(1)
    writer.append_usage(12, 3)
    writer.append_visible("notice", "已压缩上下文")
    writer.close()
    writer.close()

    events = read_events(path)
    assert [event.type for event in events] == [
        "message",
        "message",
        "message",
        "title",
        "tool_archive",
        "compact",
        "compact_failure",
        "usage",
        "notice",
    ]
    assert events[0].data["model"] == "demo-model"
    assert "model" not in events[1].data
    restored = message_from_data(events[1].data)
    assert restored is not None
    assert restored.tool_calls[0].name == "read_file"
    assert events[5].data["summary"] == "正式摘要"
    assert events[7].data == {"input_tokens": 12, "output_tokens": 3}


def test_writer_rejects_invalid_usage_values(tmp_path: Path) -> None:
    writer = ArchiveWriter(tmp_path / "session.jsonl")

    with pytest.raises(ValueError, match="非负整数"):
        writer.append_usage(-1, 0)
    with pytest.raises(ValueError, match="非负整数"):
        writer.append_usage(True, 0)
    writer.close()


def test_reader_skips_broken_tail_line(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    writer = ArchiveWriter(path)
    writer.append_message(Message(role="user", content="完整消息"), model="demo")
    writer.close()
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type":"message"')

    events = read_events(path)

    assert len(events) == 1
    assert events[0].data["content"] == "完整消息"
    assert (
        json.loads(path.read_text(encoding="utf-8").splitlines()[0])["type"]
        == "message"
    )
