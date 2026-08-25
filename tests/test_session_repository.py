from __future__ import annotations

from datetime import datetime
from pathlib import Path

import mewcode.session.archive as archive
from mewcode.llm import ImageContent, Message, ToolCall
from mewcode.session.archive import ArchiveEvent, ArchiveWriter, CompactCheckpoint
from mewcode.session.paths import paths_for
from mewcode.session.repository import SessionRepository


def write_archive(root: Path, session_id: str) -> Path:
    paths = paths_for(root, session_id)
    writer = ArchiveWriter(paths.archive_path)
    writer.append_message(Message(role="user", content="恢复这个任务"), model="demo")
    writer.append_title("恢复任务")
    writer.close()
    return paths.archive_path


def test_list_sessions_uses_archive_title_metadata_and_sorts(
    tmp_path: Path, monkeypatch
) -> None:
    timestamps = iter((1_700_000_000, 1_700_000_000, 1_700_000_100, 1_700_000_100))
    monkeypatch.setattr(archive, "_now", lambda: next(timestamps))
    older = write_archive(tmp_path, "20260701-120000-a1b2")
    newer = write_archive(tmp_path, "20260702-120000-c3d4")
    repository = SessionRepository(tmp_path)

    summaries = repository.list_sessions()

    assert [summary.session_id for summary in summaries] == [
        newer.stem,
        older.stem,
    ]
    assert summaries[0].title == "恢复任务"
    assert summaries[0].model == "demo"
    assert summaries[0].message_count == 1


def test_restore_skips_bad_rows_keeps_visible_history_and_truncates_tool_tail(
    tmp_path: Path,
) -> None:
    session_id = "20260717-120000-a1b2"
    path = paths_for(tmp_path, session_id).archive_path
    writer = ArchiveWriter(path)
    writer.append_message(Message(role="user", content="完整用户消息"), model="demo")
    writer.append_compact(CompactCheckpoint("正式摘要", 1, 1))
    writer.append_message(
        Message(role="assistant", tool_calls=[ToolCall("call-1", "read_file", "{}")])
    )
    writer.close()
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")

    restored = SessionRepository(tmp_path).restore(session_id)

    assert restored.messages == [Message(role="user", content="完整用户消息")]
    assert [event.type for event in restored.visible_events] == ["message"]
    assert restored.latest_checkpoint == CompactCheckpoint("正式摘要", 1, 1)
    assert restored.stats.turns == 1


def test_restore_sums_usage_and_counts_user_messages(tmp_path: Path) -> None:
    session_id = "20260717-120000-a1b2"
    path = paths_for(tmp_path, session_id).archive_path
    writer = ArchiveWriter(path)
    writer.append_message(Message(role="user", content="第一轮"), model="demo")
    writer.append_message(Message(role="assistant", content="完成"))
    writer.append_usage(10, 3)
    writer.append_message(Message(role="user", content="第二轮"))
    writer.append_message(Message(role="assistant", content="完成"))
    writer.append_usage(20, 7)
    writer.append(ArchiveEvent("usage", 1, {"input_tokens": -1, "output_tokens": 9}))
    writer.append(ArchiveEvent("usage", 1, {"input_tokens": True, "output_tokens": 9}))
    writer.close()

    restored = SessionRepository(tmp_path).restore(session_id)

    assert restored.stats.input_tokens == 30
    assert restored.stats.output_tokens == 10
    assert restored.stats.turns == 2


def test_cleanup_removes_only_expired_new_format_sessions_and_cache(
    tmp_path: Path,
) -> None:
    old_id = "20260601-120000-a1b2"
    current_id = "20260716-120000-c3d4"
    old_paths = paths_for(tmp_path, old_id)
    old_paths.archive_path.parent.mkdir(parents=True)
    old_paths.archive_path.write_text("", encoding="utf-8")
    old_paths.cache_dir.mkdir(parents=True)
    (old_paths.cache_dir / "result.txt").write_text("old", encoding="utf-8")
    current_path = write_archive(tmp_path, current_id)
    legacy = tmp_path / ".mewcode" / "sessions" / "1717000000-abc12345.jsonl"
    legacy.write_text("", encoding="utf-8")

    removed = SessionRepository(tmp_path).cleanup_expired(datetime(2026, 7, 17))

    assert removed == [old_id]
    assert not old_paths.archive_path.exists()
    assert not old_paths.cache_dir.exists()
    assert current_path.exists()
    assert legacy.exists()


def test_delete_removes_session_and_cache_but_keeps_memory(tmp_path: Path) -> None:
    session_id = "20260717-120000-a1b2"
    archive_path = write_archive(tmp_path, session_id)
    paths = paths_for(tmp_path, session_id)
    paths.cache_dir.mkdir(parents=True)
    (paths.cache_dir / "tool.txt").write_text("cached", encoding="utf-8")
    memory = tmp_path / ".mewcode" / "memory" / "project_note.md"
    memory.parent.mkdir(parents=True)
    memory.write_text("retain", encoding="utf-8")

    deleted = SessionRepository(tmp_path).delete(session_id)

    assert deleted is True
    assert not archive_path.exists()
    assert not paths.cache_dir.exists()
    assert memory.read_text(encoding="utf-8") == "retain"


def test_delete_rejects_legacy_or_missing_session(tmp_path: Path) -> None:
    repository = SessionRepository(tmp_path)

    assert repository.delete("1717000000-abc12345") is False
    assert repository.delete("20260717-120000-a1b2") is False


def test_reserve_image_bytes_clears_oldest_data_and_keeps_metadata(
    tmp_path: Path,
) -> None:
    session_id = "20260717-120000-a1b2"
    path = paths_for(tmp_path, session_id).archive_path
    writer = ArchiveWriter(path)
    for index in range(2):
        writer.append_message(
            Message(
                role="user",
                content=f"图 {index}",
                images=[
                    ImageContent(
                        media_type="image/png",
                        data="eA==",
                        sha256=f"hash-{index}",
                        width=10,
                        height=20,
                        size_bytes=4,
                        created_at=index,
                    )
                ],
            )
        )
    writer.close()

    repository = SessionRepository(tmp_path)
    assert repository.reserve_image_bytes(session_id, 4, limit_bytes=8)

    restored = repository.restore(session_id).messages
    assert restored[0].images[0].cleared is True
    assert restored[0].images[0].data == ""
    assert restored[0].images[0].sha256 == "hash-0"
    assert restored[0].images[0].width == 10
    assert restored[1].images[0].data == "eA=="


def test_reserve_image_bytes_rejects_unfit_batch_without_rewriting(
    tmp_path: Path,
) -> None:
    session_id = "20260717-120000-a1b2"
    path = write_archive(tmp_path, session_id)
    before = path.read_bytes()

    assert not SessionRepository(tmp_path).reserve_image_bytes(
        session_id, 9, limit_bytes=8
    )
    assert path.read_bytes() == before
