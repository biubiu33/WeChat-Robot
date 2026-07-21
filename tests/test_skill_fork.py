from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from mewcode.llm import Request, StreamEvent
from mewcode.permission import Mode, new_engine
from mewcode.skill import ActiveSkill, ForkSkillRunner
from mewcode.tool import Registry


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.requests: list[Request] = []

    def redact(self, text: str) -> str:
        return text.replace("secret", "***")

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            yield StreamEvent(text="执行完成，secret 不应泄漏")
        else:
            yield StreamEvent(text="简短摘要")
        yield StreamEvent(done=True)


def test_fork_uses_only_argument_and_returns_summary(tmp_path: Path) -> None:
    provider = FakeProvider()
    engine, error = new_engine(tmp_path)
    assert error is None
    runner = ForkSkillRunner(Registry(), engine, Mode.DEFAULT)
    skill = ActiveSkill("test", "只带这个参数", "执行 SOP", frozenset(), None)

    summary = asyncio.run(runner.run(skill, provider))

    assert summary.text == "简短摘要"
    first = provider.requests[0]
    assert [message.content for message in first.messages] == ["只带这个参数"]
    assert first.system.environment.startswith("# 已激活 Skill")
    assert "执行 SOP" in first.system.environment
    assert "主对话" not in first.system.environment


def test_fork_cancellation_returns_cancel_notice(tmp_path: Path) -> None:
    provider = FakeProvider()
    engine, error = new_engine(tmp_path)
    assert error is None
    cancel = asyncio.Event()
    cancel.set()
    runner = ForkSkillRunner(Registry(), engine)
    skill = ActiveSkill("test", "argument", "SOP", frozenset(), None)

    summary = asyncio.run(runner.run(skill, provider, cancel))

    assert "已取消" in summary.text
    assert provider.requests == []
