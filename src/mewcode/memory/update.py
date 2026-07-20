"""自动记忆的无工具更新任务。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mewcode.llm import Message, Provider
from mewcode.llm.generation import generate_text

from .store import MemoryStore, NoteOperation


MEMORY_SYSTEM = "你是记忆整理器。禁止调用工具，只返回合法 JSON。"


class MemoryManager:
    def __init__(self, root: Path, home: Path | None = None) -> None:
        self._store = MemoryStore(root, home)

    def prompt_index(self) -> str:
        return self._store.prompt_index()

    def indexed_files(self) -> dict[str, tuple[str, ...]]:
        return self._store.indexed_files()

    async def update_after_turn(
        self, turn_messages: list[Message], provider: Provider
    ) -> None:
        try:
            text = await generate_text(
                provider,
                system=MEMORY_SYSTEM,
                prompt=_update_prompt(turn_messages, self._store.prompt_index()),
            )
            operations, indexes = _parse_update(text)
            await self._store.apply(operations, indexes)
        except Exception as exc:
            redact = getattr(provider, "redact", None)
            message = redact(str(exc)) if callable(redact) else str(exc)
            print(f"[memory] warn: update skipped: {message}", file=sys.stderr)


def _update_prompt(messages: list[Message], index: str) -> str:
    transcript = "\n".join(
        f"[{message.role}] {message.content}" for message in messages
    )
    return (
        "根据本轮对话提取值得长期记住的信息。仅返回 JSON 对象："
        '{"operations":[{"action":"create|update","level":"user|project",'
        '"type":"user|feedback|project|reference","title":"...",'
        '"filename":"lowercase_slug.md","content":"..."}],'
        '"indexes":{"user":"...","project":"..."}}。'
        '没有更新时返回 {"operations":[]}。不要删除笔记。\n'
        f"现有索引：\n{index}\n本轮：\n{transcript}"
    )


def _parse_update(text: str) -> tuple[list[NoteOperation], dict[str, str]]:
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("记忆更新不是对象")
    raw_operations = raw.get("operations", [])
    if not isinstance(raw_operations, list):
        raise ValueError("operations 必须是数组")
    operations: list[NoteOperation] = []
    for item in raw_operations:
        if not isinstance(item, dict):
            raise ValueError("记忆操作必须是对象")
        values = tuple(
            item.get(key)
            for key in ("action", "level", "type", "title", "filename", "content")
        )
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError("记忆操作字段不完整")
        action, level, note_type, title, filename, content = values
        if action not in {"create", "update"}:
            raise ValueError("不允许删除记忆")
        operations.append(
            NoteOperation(action, level, note_type, title, filename, content)
        )  # type: ignore[arg-type]
    indexes_raw = raw.get("indexes", {})
    if not isinstance(indexes_raw, dict):
        raise ValueError("indexes 必须是对象")
    indexes = {
        key: value
        for key, value in indexes_raw.items()
        if key in {"user", "project"} and isinstance(value, str)
    }
    return operations, indexes


__all__ = ["MemoryManager"]
