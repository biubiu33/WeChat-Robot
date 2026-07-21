from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from mewcode.tool import Result, error_result, parse_arguments, require_string

from .install import InstalledSkill, SkillInstaller
from .model import ActiveSkill, SkillError, SkillMode, SkillValidationError
from .runtime import SkillRuntime


class ForkExecutor(Protocol):
    async def run(self, skill: ActiveSkill) -> str: ...


class LoadSkillTool:
    read_only = True
    system = True

    def __init__(
        self, runtime: SkillRuntime, fork_executor: ForkExecutor | None = None
    ) -> None:
        self._runtime = runtime
        self._fork_executor = fork_executor

    def name(self) -> str:
        return "load_skill"

    def description(self) -> str:
        return "按名称加载可用 Skill 的完整 SOP；fork Skill 会隔离执行并返回摘要。"

    def parameters(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Skill 名称"},
                "argument": {"type": "string", "description": "Skill 参数"},
            },
            "required": ["name"],
        }

    async def execute(self, args: str) -> Result:
        values, error = parse_arguments(args)
        if error is not None:
            return error
        name, error = require_string(values or {}, "name")
        if error is not None:
            return error
        argument = (values or {}).get("argument", "")
        if not isinstance(argument, str):
            return error_result("invalid_arguments", "参数 argument 必须是字符串")
        skill = self._runtime.catalog.get(name or "")
        if skill is None:
            return error_result("skill_not_found", f"未找到 Skill: {name}")
        try:
            if skill.metadata.mode is SkillMode.INLINE:
                active = self._runtime.activate_inline(name or "", argument)
                return Result(active.instruction)
            active = self._runtime.prepare_fork(name or "", argument)
            if self._fork_executor is None:
                return error_result("fork_unavailable", "当前环境不支持 fork Skill")
            return Result(await self._fork_executor.run(active))
        except SkillError as exc:
            return error_result("skill_load_failed", str(exc))


class InstallSkillTool:
    read_only = False
    system = True

    def __init__(
        self,
        installer: SkillInstaller,
        refresh: Callable[[], object] | None = None,
    ) -> None:
        self._installer = installer
        self._refresh = refresh

    def name(self) -> str:
        return "install_skill"

    def description(self) -> str:
        return "从 HTTPS URL 或本地 ZIP 安装用户级 Skill。"

    def parameters(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"source": {"type": "string", "description": "ZIP 来源"}},
            "required": ["source"],
        }

    async def execute(self, args: str) -> Result:
        values, error = parse_arguments(args)
        if error is not None:
            return error
        source, error = require_string(values or {}, "source")
        if error is not None:
            return error
        try:
            installed = await asyncio.to_thread(self._installer.install, source or "")
        except SkillValidationError as exc:
            return error_result("skill_install_failed", str(exc))
        if self._refresh is not None:
            self._refresh()
        return Result(_installed_message(installed))


def _installed_message(installed: InstalledSkill) -> str:
    return f"已安装 Skill: {installed.skill.metadata.name}\n位置: {installed.path}"


__all__ = ["ForkExecutor", "InstallSkillTool", "LoadSkillTool"]
