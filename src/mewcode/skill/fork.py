from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mewcode.agent import Agent, NOTICE_CANCELLED
from mewcode.conversation import Conversation
from mewcode.llm import Provider
from mewcode.llm.generation import generate_text
from mewcode.permission import Engine, Mode
from mewcode.tool import Registry

from .model import ActiveSkill


SUMMARY_SYSTEM = "你是 Skill 执行摘要器。禁止调用工具，只输出简短、准确的结果摘要。"
SUMMARY_LIMIT = 1_000


@dataclass(frozen=True)
class ForkSummary:
    text: str


class ForkSkillRunner:
    def __init__(
        self, registry: Registry, engine: Engine, mode: Mode = Mode.DEFAULT
    ) -> None:
        self._registry = registry
        self._engine = engine
        self._mode = mode

    async def run(
        self,
        skill: ActiveSkill,
        provider: Provider,
        cancel: asyncio.Event | None = None,
    ) -> ForkSummary:
        cancelled = cancel if cancel is not None else asyncio.Event()
        conversation = Conversation()
        conversation.add_user(skill.argument)
        agent = Agent(
            provider,
            self._registry,
            engine=self._engine,
            prompt_supplier=lambda: ("", "", ""),
            environment_supplier=lambda environment: _environment(skill, environment),
            tool_policy_supplier=lambda: skill.allowed_tools,
        )
        async for _ in agent.run(conversation, self._mode, cancelled):
            pass
        result = conversation.messages()[-1].content if len(conversation) else ""
        if cancelled.is_set() or result == NOTICE_CANCELLED:
            return ForkSummary(NOTICE_CANCELLED)
        return ForkSummary(await _summary(provider, result))


def _environment(skill: ActiveSkill, environment: str) -> str:
    return f"# 已激活 Skill\n\n## {skill.name}\n{skill.instruction}\n\n{environment}"


async def _summary(provider: Provider, result: str) -> str:
    try:
        return await generate_text(
            provider,
            system=SUMMARY_SYSTEM,
            prompt=f"请总结以下 Skill 执行结果：\n{result}",
        )
    except Exception:
        return provider.redact(result)[:SUMMARY_LIMIT] or "Skill 未返回可用结果"


__all__ = ["ForkSkillRunner", "ForkSummary"]
