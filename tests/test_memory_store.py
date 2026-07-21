from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mewcode.memory.store import MAX_INDEX_BYTES, MemoryStore, NoteOperation


def operation(note_type: str, level: str, filename: str) -> NoteOperation:
    return NoteOperation("create", level, note_type, "偏好标题", filename, "简洁回复")  # type: ignore[arg-type]


def test_store_writes_levels_frontmatter_and_prompt_index(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "project", tmp_path / "home")
    asyncio.run(
        store.apply(
            [
                operation("user", "user", "user_style.md"),
                operation("project", "project", "project_api.md"),
            ]
        )
    )

    user_note = tmp_path / "home" / ".mewcode" / "memory" / "user_style.md"
    project_note = tmp_path / "project" / ".mewcode" / "memory" / "project_api.md"
    assert "type: user" in user_note.read_text(encoding="utf-8")
    assert "type: project" in project_note.read_text(encoding="utf-8")
    index = store.prompt_index()
    assert index.index("[project]") < index.index("[user]")


def test_store_rejects_invalid_level_and_filename(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "project", tmp_path / "home")
    with pytest.raises(ValueError):
        asyncio.run(store.apply([operation("user", "project", "bad.md")]))
    with pytest.raises(ValueError):
        asyncio.run(store.apply([operation("user", "user", "../bad.md")]))


def test_store_truncates_large_injected_index(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "project", tmp_path / "home")
    memory_dir = tmp_path / "project" / ".mewcode" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("x" * (MAX_INDEX_BYTES + 1), encoding="utf-8")

    assert store.prompt_index().endswith("(index truncated)\n")


def test_store_repairs_empty_index_from_existing_notes(tmp_path: Path) -> None:
    memory_dir = tmp_path / "project" / ".mewcode" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("项目标题\n", encoding="utf-8")
    (memory_dir / "project_stack.md").write_text(
        "---\n"
        "type: project\n"
        "title: 技术栈\n"
        "created: 2026-07-21T00:00:00+08:00\n"
        "updated: 2026-07-21T00:00:00+08:00\n"
        "---\n"
        "使用 FastAPI 和 PostgreSQL。\n",
        encoding="utf-8",
    )

    store = MemoryStore(tmp_path / "project", tmp_path / "home")

    assert store.prompt_index() == (
        "- [project] 技术栈 — 使用 FastAPI 和 PostgreSQL。 <!-- project_stack.md -->\n"
    )


def test_store_lists_indexed_files_by_level_without_reading_notes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    project_memory = project / ".mewcode" / "memory"
    user_memory = home / ".mewcode" / "memory"
    project_memory.mkdir(parents=True)
    user_memory.mkdir(parents=True)
    (project_memory / "MEMORY.md").write_text(
        "- project B <!-- project_b.md -->\n"
        "- project A <!-- project_a.md -->\n"
        "- duplicate <!-- project_a.md -->\n"
        "- unsafe <!-- ../secret.md -->\n"
        "ordinary text secret-content\n",
        encoding="utf-8",
    )
    (user_memory / "MEMORY.md").write_text(
        "- user <!-- user_style.md -->\n",
        encoding="utf-8",
    )
    store = MemoryStore(project, home)

    assert store.indexed_files() == {
        "project": ("project_a.md", "project_b.md"),
        "user": ("user_style.md",),
    }


def test_store_lists_empty_index_levels(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "project", tmp_path / "home")

    assert store.indexed_files() == {"project": (), "user": ()}
