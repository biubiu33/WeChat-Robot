from __future__ import annotations

from typing import TYPE_CHECKING

from mewcode.command import (
    MemorySnapshot,
    SessionSnapshot,
    SkillSnapshot,
    SkillsSnapshot,
    StatusSnapshot,
)
from mewcode.permission import Mode
from mewcode.session import SessionStats
from mewcode.session.runtime import SessionRuntime
from mewcode.skill import SkillError, SkillMode

from .timeline import Timeline
from .view import command_output_entry, notice_entry

if TYPE_CHECKING:
    from .app import MewCodeApp


class TuiCommandControl:
    def __init__(self, app: MewCodeApp) -> None:
        self.app = app

    async def show_message(self, text: str) -> None:
        await self.app.append_timeline(command_output_entry(text))

    async def send_user_message(self, text: str) -> None:
        await self.app.start_user_turn(text)

    async def compact_context(self) -> None:
        await self.app.action_compact()

    async def resume_session(self) -> None:
        await self.app.action_resume()

    async def clear_session(self) -> None:
        if self.app.provider is None or self.app.provider_config is None:
            await self.show_message("尚未选择 Provider")
            return
        if self.app.runtime is not None:
            self.app.runtime.close()
        self.app.skill_runtime.clear()
        self.app.runtime = SessionRuntime.new(
            self.app.root,
            self.app.provider,
            self.app.provider_config.context_window,
            enable_title=self.app.session_enabled,
        )
        self.app.conv = self.app.runtime.conversation
        self.app.session_stats = SessionStats()
        timeline = self.app.query_one("#timeline", Timeline)
        await timeline.clear()
        message = "已结束当前会话并开启新会话"
        await timeline.append(notice_entry(message))
        self.app.runtime.writer.append_visible("notice", message)
        self.app.refresh_status()
        self.app.query_one("#input").focus()

    async def exit_app(self) -> None:
        await self.app.action_quit()

    def set_mode(self, mode: Mode) -> None:
        self.app.mode = mode

    def refresh_status(self) -> None:
        self.app.refresh_status()

    def status_snapshot(self) -> StatusSnapshot:
        memory = self.memory_snapshot()
        definitions = self.app.current_definitions()
        return StatusSnapshot(
            str(self.app.mode),
            self.app.session_stats.input_tokens,
            self.app.session_stats.output_tokens,
            len(definitions),
            memory.total,
            self.app.provider.model if self.app.provider is not None else "",
            str(self.app.root),
        )

    def memory_snapshot(self) -> MemorySnapshot:
        indexed = self.app.memory_manager.indexed_files()
        return MemorySnapshot(
            tuple(indexed.get("project", ())),
            tuple(indexed.get("user", ())),
        )

    def session_snapshot(self) -> SessionSnapshot | None:
        if self.app.runtime is None:
            return None
        return SessionSnapshot(
            self.app.runtime.paths.session_id,
            str(self.app.runtime.paths.archive_path.resolve()),
        )

    def skills_snapshot(self) -> SkillsSnapshot:
        active = {skill.name for skill in self.app.skill_runtime.active_skills()}
        skills = tuple(
            SkillSnapshot(
                skill.metadata.name,
                skill.metadata.description,
                skill.source.value,
                skill.metadata.name in active,
            )
            for skill in self.app.skill_runtime.catalog.effective()
        )
        diagnostics = tuple(
            f"{item.path}: {item.message}"
            for item in self.app.skill_runtime.catalog.diagnostics()
        )
        return SkillsSnapshot(skills, diagnostics)

    async def run_skill(self, name: str, argument: str) -> None:
        notice = self.app.refresh_skills()
        if notice is not None:
            await self.show_message(notice)
        skill = self.app.skill_runtime.catalog.get(name)
        if skill is None:
            await self.show_message(f"未找到 Skill: {name}")
            return
        try:
            if skill.metadata.mode is SkillMode.INLINE:
                self.app.skill_runtime.activate_inline(name, argument)
                await self.app.start_user_turn(argument)
                return
            await self.app.start_fork_skill(
                self.app.skill_runtime.prepare_fork(name, argument)
            )
        except SkillError as exc:
            await self.show_message(f"Skill 执行失败: {exc}")
