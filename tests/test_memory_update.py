from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.llm import Message, StreamEvent
from mewcode.memory.update import MemoryManager


class ProviderStub:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests = []

    def redact(self, text: str) -> str:
        return text

    def stream(self, request):
        self.requests.append(request)

        async def events():
            yield StreamEvent(text=self.response)

        return events()


def test_memory_update_writes_note_without_tools(tmp_path: Path) -> None:
    provider = ProviderStub(
        '{"operations":[{"action":"create","level":"user","type":"user",'
        '"title":"中文回复","filename":"user_chinese_reply.md","content":"用户偏好中文。"}]}'
    )
    manager = MemoryManager(tmp_path / "project", tmp_path / "home")

    asyncio.run(
        manager.update_after_turn([Message(role="user", content="请用中文")], provider)
    )

    assert provider.requests[0].tools == []
    assert (
        tmp_path / "home" / ".mewcode" / "memory" / "user_chinese_reply.md"
    ).exists()


def test_memory_update_swallows_invalid_json(tmp_path: Path) -> None:
    manager = MemoryManager(tmp_path / "project", tmp_path / "home")
    asyncio.run(manager.update_after_turn([], ProviderStub("not json")))

    assert manager.prompt_index() == ""
