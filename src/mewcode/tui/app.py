from __future__ import annotations

import asyncio
import os
import time
from dataclasses import replace
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.containers import Container
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import OptionList, Static, TextArea

from mewcode.agent import ApprovalRequest
from mewcode import __version__
from mewcode.command import (
    CommandConflictError,
    CommandDispatcher,
    CommandRegistry,
    InputKind,
    new_skill_commands,
    new_default_command_registry,
    parse_input,
)
from mewcode.config import ProviderConfig
from mewcode.conversation import Conversation
from mewcode.hook import HookContext, HookDispatch, HookEngine, HookEvent
from mewcode.llm import Provider, new_provider
from mewcode.memory import InstructionBundle, MemoryManager
from mewcode.permission import Engine, Mode, Outcome, new_engine
from mewcode.prompt import gather_environment, render_banner
from mewcode.session import SessionStats
from mewcode.session.repository import SessionRepository
from mewcode.skill import (
    ActiveSkill,
    ForkSkillRunner,
    InstallSkillTool,
    LoadSkillTool,
    SkillCatalog,
    SkillInstaller,
    SkillRuntime,
    SkillValidationError,
)
from mewcode.session.runtime import SessionRuntime
from mewcode.tool import Registry, new_default_registry

from .completion import CommandCompletionMenu
from .timeline import Timeline, ToolRun
from .view import (
    notice_entry,
    selecting_status,
    status_bar,
    system_entry,
    user_entry,
)


class SessionState(Enum):
    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"
    APPROVING = "approving"
    FORKING = "forking"
    COMPACTING = "compacting"
    RESUMING = "resuming"


class PromptInput(TextArea):
    def on_key(self, event: events.Key) -> None:
        app = self.app
        if event.key == "shift+tab":
            if hasattr(app, "action_cycle_permission_mode"):
                asyncio.create_task(app.action_cycle_permission_mode())
            event.prevent_default()
            event.stop()
            return

        if event.key == "tab":
            app = self.app
            if hasattr(app, "complete_current_input"):
                app.complete_current_input()
            event.prevent_default()
            event.stop()
            return

        if event.key in {"up", "down"} and hasattr(app, "command_menu_visible"):
            if app.command_menu_visible():
                app.move_command_menu(-1 if event.key == "up" else 1)
                event.prevent_default()
                event.stop()
                return

        if event.key == "escape" and hasattr(app, "command_menu_visible"):
            if app.command_menu_visible():
                app.dismiss_command_menu()
                event.prevent_default()
                event.stop()
                return

        if event.key in {"alt+enter", "meta+enter"}:
            self.insert("\n")
            event.prevent_default()
            return

        if event.key == "enter":
            if (
                hasattr(app, "refresh_command_menu")
                and hasattr(app, "command_menu_visible")
                and not app.command_menu_visible()
            ):
                app.refresh_command_menu()
            if hasattr(app, "command_menu_visible") and app.command_menu_visible():
                app.accept_command_completion()
                event.prevent_default()
                event.stop()
                return
            if hasattr(app, "submit_current_input"):
                asyncio.create_task(app.submit_current_input())
            event.prevent_default()


class MewCodeApp(App):
    CSS = """
    Screen {
        background: $surface;
        color: $text;
    }

    #selector {
        height: 1fr;
        padding: 1 2;
    }

    #main {
        height: 1fr;
        layout: vertical;
    }

    #timeline {
        height: 1fr;
        padding: 1 2;
        scrollbar-gutter: stable;
    }

    #streaming {
        height: auto;
        max-height: 12;
        padding: 0 2;
        border-top: solid $boost;
        overflow-y: auto;
    }

    #input {
        height: 5;
        margin: 0 1;
        border: round $primary;
        padding: 0 1;
    }

    #command-completion-menu {
        height: auto;
        max-height: 12;
        margin: 0 1;
        border: round $secondary;
        background: $surface;
        overflow-y: auto;
        scrollbar-gutter: stable;
    }

    #statusbar {
        height: 1;
        padding: 0 2;
        background: $boost;
    }

    .timeline-entry {
        width: 100%;
        margin: 0 0 1 0;
        padding: 0 1;
    }

    .user-entry {
        background: $boost;
        border-left: heavy $primary;
        color: $text;
    }

    .assistant-entry {
        border-left: heavy $success;
    }

    .tool-result-entry {
        border-left: heavy $accent;
        background: $surface;
    }

    .tool-result-entry-error {
        border-left: heavy $error;
    }

    .tool-result-detail {
        padding: 0 1;
    }

    .tool-result-error {
        color: $error;
    }

    .notice-entry {
        border-left: heavy $warning;
    }

    .error-entry {
        background: $boost;
        border-left: heavy $error;
    }

    .system-entry {
        border-left: heavy $secondary;
    }

    .command-output-entry {
        border-left: heavy $secondary;
    }
    """

    BINDINGS = [
        ("ctrl+c", "cancel_or_quit", "取消/退出"),
        ("escape", "cancel_turn", "取消当前回合"),
        ("shift+tab", "cycle_permission_mode", "切换权限模式"),
    ]

    def __init__(
        self,
        providers: list[ProviderConfig],
        version: str = __version__,
        registry: Registry | None = None,
        command_registry: CommandRegistry | None = None,
        engine: Engine | None = None,
        root: Path | None = None,
        instructions: InstructionBundle | None = None,
        memory_manager: MemoryManager | None = None,
        session_repository: SessionRepository | None = None,
        skill_runtime: SkillRuntime | None = None,
        hook_engine: HookEngine | None = None,
    ) -> None:
        super().__init__()
        self.providers = providers
        self.version = version
        self.registry = registry if registry is not None else new_default_registry()
        self.root = (Path.cwd() if root is None else root).resolve()
        self.engine = engine if engine is not None else new_engine(os.getcwd())[0]
        self.hook_engine = hook_engine if hook_engine is not None else HookEngine()
        self.skill_runtime = skill_runtime or SkillRuntime(
            SkillCatalog.load(self.root), self.registry.ordinary_names()
        )
        self._skill_command_names: tuple[str, ...] = ()
        self._skill_provider_cache: dict[str, Provider] = {}
        self.command_registry = (
            command_registry
            if command_registry is not None
            else new_default_command_registry()
        )
        self._register_skill_tools()
        error = self.refresh_skills()
        if error is not None:
            raise RuntimeError(error)
        self.command_dispatcher = CommandDispatcher(self.command_registry)
        self.instructions = (
            instructions if instructions is not None else InstructionBundle("")
        )
        self.memory_manager = (
            memory_manager if memory_manager is not None else MemoryManager(self.root)
        )
        self.memory_enabled = memory_manager is not None
        self.session_repository = (
            session_repository
            if session_repository is not None
            else SessionRepository(self.root)
        )
        self.session_enabled = session_repository is not None
        self.state = SessionState.SELECTING if len(providers) > 1 else SessionState.IDLE
        self.provider: Provider | None = None
        self.provider_config: ProviderConfig | None = None
        self.conv = Conversation()
        self.runtime: SessionRuntime | None = None
        self.mode = self.engine.default_mode
        self.iter = 0
        self.session_stats = SessionStats()
        self.cur_reply = ""
        self.cur_tools: list[ToolRun] = []
        self.turn_start = 0.0
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None
        self.turn_cancel: asyncio.Event | None = None
        self.pending: ApprovalRequest | None = None
        self.approve_cursor = 0
        self._completion_suppressed_text: str | None = None
        from .command import TuiCommandControl

        self.command_control = TuiCommandControl(self)

    def _register_skill_tools(self) -> None:
        tools = (
            LoadSkillTool(self.skill_runtime, _AppForkExecutor(self)),
            InstallSkillTool(
                SkillInstaller(
                    self.skill_runtime.catalog.user_root,
                    set(self.registry.ordinary_names()),
                ),
                self.refresh_skills,
            ),
        )
        for tool in tools:
            existing = self.registry.get(tool.name())
            if existing is None:
                self.registry.register(tool)
                continue
            if not getattr(existing, "system", False):
                raise RuntimeError(f"系统工具名称冲突: {tool.name()}")

    def refresh_skills(self) -> str | None:
        """Reload changed Skills and atomically rebuild their slash commands."""
        try:
            refresh = self.skill_runtime.refresh()
        except SkillValidationError as exc:
            return f"Skill 热更新失败: {exc}"

        commands = new_skill_commands(
            tuple(
                (skill.metadata.name, skill.metadata.description)
                for skill in self.skill_runtime.catalog.effective()
            )
        )
        try:
            self.command_registry.replace_dynamic(self._skill_command_names, commands)
        except CommandConflictError as exc:
            return f"Skill 命令注册失败: {exc}"
        self._skill_command_names = tuple(command.name for command in commands)

        if refresh.removed:
            return "已移除失效的活动 Skill: " + ", ".join(refresh.removed)
        return None

    def skill_environment(self, environment: str) -> str:
        active = self.skill_runtime.active_environment()
        return f"{active}\n\n{environment}" if active else environment

    def current_definitions(self):
        allowed = self.skill_runtime.ordinary_allowed_tools()
        if self.mode is Mode.PLAN:
            return self.registry.read_only_definitions(allowed)
        return self.registry.definitions(allowed)

    def provider_for_skill(self, model: str | None) -> Provider:
        if self.provider is None:
            raise RuntimeError("尚未选择 Provider")
        if (
            model is None
            or self.provider_config is None
            or model == self.provider_config.model
        ):
            return self.provider
        cached = self._skill_provider_cache.get(model)
        if cached is None:
            cached = new_provider(replace(self.provider_config, model=model))
            self._skill_provider_cache[model] = cached
        return cached

    def compose(self) -> ComposeResult:
        yield Container(
            Static(render_banner(self.version, os.getcwd()), id="selector-banner"),
            Static(Text("选择本次会话使用的 provider", style="bold")),
            OptionList(
                *[f"{provider.name} ({provider.model})" for provider in self.providers],
                id="provider-list",
            ),
            id="selector",
        )
        yield Container(
            Timeline(id="timeline"),
            Static("", id="streaming"),
            PromptInput(placeholder="输入消息...", id="input"),
            CommandCompletionMenu(id="command-completion-menu"),
            Static("", id="statusbar"),
            id="main",
        )

    async def on_mount(self) -> None:
        await self.append_timeline(
            system_entry(render_banner(self.version, os.getcwd()))
        )

        if len(self.providers) == 1:
            self.activate_provider(self.providers[0])
            self.query_one("#selector").display = False
            self.refresh_status()
            self.query_one("#input").focus()
        else:
            self.query_one("#main").display = False
            self.query_one("#statusbar", Static).update(selecting_status())
            provider_list = self.query_one("#provider-list", OptionList)
            provider_list.highlighted = 0
            provider_list.focus()

    async def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option_list.id == "command-completion-menu":
            event.stop()
            self.accept_command_completion(event.option_index)
            return
        if event.option_list.id != "provider-list":
            return
        from .select import select_provider

        select_provider(self, event.option_index, SessionState.IDLE)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "input":
            self.refresh_command_menu()

    async def submit_current_input(self) -> None:
        if self.state is not SessionState.IDLE:
            return

        notice = self.refresh_skills()
        if notice is not None:
            await self.append_timeline(notice_entry(notice))

        text_area = self.query_one("#input", TextArea)
        parsed = parse_input(text_area.text)
        if parsed.kind is InputKind.EMPTY:
            return
        if parsed.kind is InputKind.COMMAND:
            text_area.text = ""
            await self.command_dispatcher.dispatch(parsed, self.command_control)
            if self.state is SessionState.IDLE:
                text_area.focus()
            return
        await self.start_user_turn(parsed.text)

    def complete_current_input(self) -> None:
        if not self.command_menu_visible():
            self.refresh_command_menu()
        if self.command_menu_visible():
            self.accept_command_completion()

    def refresh_command_menu(self) -> None:
        self.refresh_skills()
        text_area = self.query_one("#input", TextArea)
        menu = self.query_one("#command-completion-menu", CommandCompletionMenu)
        text = text_area.text

        if self._completion_suppressed_text is not None:
            if text == self._completion_suppressed_text:
                menu.set_commands(())
                return
            self._completion_suppressed_text = None

        if (
            self.state is not SessionState.IDLE
            or not text.startswith("/")
            or any(character.isspace() for character in text[1:])
        ):
            menu.set_commands(())
            return

        menu.set_commands(self.command_registry.completions(text[1:]))

    def command_menu_visible(self) -> bool:
        menu = self.query_one("#command-completion-menu", CommandCompletionMenu)
        return bool(menu.display and menu.commands)

    def move_command_menu(self, delta: int) -> None:
        menu = self.query_one("#command-completion-menu", CommandCompletionMenu)
        menu.move_highlight(delta)

    def dismiss_command_menu(self) -> None:
        text_area = self.query_one("#input", TextArea)
        self._completion_suppressed_text = text_area.text
        self.query_one("#command-completion-menu", CommandCompletionMenu).set_commands(
            ()
        )
        text_area.focus()

    def accept_command_completion(self, option_index: int | None = None) -> None:
        menu = self.query_one("#command-completion-menu", CommandCompletionMenu)
        command_name = (
            menu.highlighted_name()
            if option_index is None
            else menu.command_name_at(option_index)
        )
        if command_name is None:
            return
        self._apply_completion(command_name)

    def _apply_completion(self, command_name: str) -> None:
        text_area = self.query_one("#input", TextArea)
        completed_text = f"/{command_name}"
        self._completion_suppressed_text = completed_text
        self.query_one("#command-completion-menu", CommandCompletionMenu).set_commands(
            ()
        )
        text_area.text = completed_text
        text_area.cursor_location = (0, len(completed_text))
        text_area.focus()

    async def start_user_turn(self, text: str) -> None:
        if self.state is not SessionState.IDLE:
            return
        if self.provider is None:
            return
        created = self._ensure_runtime()
        if created:
            await self.dispatch_hook(HookEvent.SESSION_START, {})
        dispatch = await self.dispatch_hook(
            HookEvent.USER_PROMPT_SUBMIT, {"prompt": text}
        )
        if dispatch.blocked:
            await self.append_timeline(
                notice_entry(f"[hook {dispatch.blocked_by}] {dispatch.reason}")
            )
            self.query_one("#input", TextArea).focus()
            return
        self.conv.add_user(text)
        self.session_stats.turns += 1
        await self.append_timeline(user_entry(text))
        text_area = self.query_one("#input", TextArea)
        text_area.text = ""
        text_area.read_only = True
        self.cur_reply = ""
        self.cur_tools = []
        self.iter = 0
        self.turn_cancel = asyncio.Event()
        self.turn_start = time.monotonic()
        self.state = SessionState.STREAMING
        self.refresh_status()

        from .stream import consume_stream, tick

        self._timer = self.set_interval(0.1, lambda: tick(self, SessionState.STREAMING))
        self._stream_task = asyncio.create_task(consume_stream(self))

    async def start_fork_skill(self, skill: ActiveSkill) -> None:
        if self.state is not SessionState.IDLE or self.provider is None:
            return
        created = self._ensure_runtime()
        if created:
            await self.dispatch_hook(HookEvent.SESSION_START, {})
        invocation = f"执行 Skill {skill.name}: {skill.argument}".rstrip()
        self.conv.add_user(invocation)
        self.session_stats.turns += 1
        await self.append_timeline(user_entry(invocation))
        text_area = self.query_one("#input", TextArea)
        text_area.text = ""
        text_area.read_only = True
        self.turn_cancel = asyncio.Event()
        self.turn_start = time.monotonic()
        self.state = SessionState.FORKING
        self.refresh_status()
        self.query_one("#streaming", Static).update(
            f"正在隔离执行 Skill {skill.name}..."
        )
        self._stream_task = asyncio.create_task(self._consume_fork_skill(skill))

    async def _consume_fork_skill(self, skill: ActiveSkill) -> None:
        from .stream import finish_with_assistant, finish_with_error

        try:
            summary = await self.run_fork_skill(skill)
        except Exception as exc:
            await finish_with_error(self, exc)
            return
        await finish_with_assistant(self, summary)

    async def run_fork_skill(self, skill: ActiveSkill) -> str:
        runner = ForkSkillRunner(self.registry, self.engine, self.mode)
        summary = await runner.run(
            skill,
            self.provider_for_skill(skill.model),
            self.turn_cancel,
        )
        return summary.text

    def activate_provider(self, cfg: ProviderConfig) -> None:
        self.provider = new_provider(cfg)
        self.provider_config = cfg
        self.skill_runtime.clear()
        self._skill_provider_cache.clear()
        if self.runtime is not None:
            self.runtime.close()
        self.runtime = None
        self.conv = Conversation()
        self.session_stats = SessionStats()

    def _ensure_runtime(self) -> bool:
        if self.runtime is not None:
            return False
        if self.provider is None or self.provider_config is None:
            raise RuntimeError("尚未选择 Provider")
        self.runtime = SessionRuntime.new(
            self.root,
            self.provider,
            self.provider_config.context_window,
            enable_title=self.session_enabled,
        )
        self.runtime.context.set_hook_dispatcher(self.dispatch_hook)
        self.conv = self.runtime.conversation
        return True

    def hook_context(self, event: HookEvent, fields: dict[str, object]) -> HookContext:
        session_id = self.runtime.paths.session_id if self.runtime is not None else ""
        return HookContext(
            event,
            {
                "event": event.value,
                "session_id": session_id,
                "cwd": str(self.root),
                "mode": str(self.mode),
                **fields,
            },
        )

    async def dispatch_hook(
        self, event: HookEvent, fields: dict[str, object]
    ) -> HookDispatch:
        if self.runtime is None:
            return HookDispatch()
        return await self.hook_engine.dispatch(
            event, self.hook_context(event, fields), self.runtime.hook_state
        )

    async def _close_runtime(self) -> None:
        if self.runtime is None:
            return
        await self.dispatch_hook(HookEvent.SESSION_END, {})
        await self.hook_engine.close_session(self.runtime.hook_state)
        self.runtime.close()
        self.runtime = None

    @property
    def usage_in(self) -> int:
        return self.session_stats.input_tokens

    @property
    def usage_out(self) -> int:
        return self.session_stats.output_tokens

    def record_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.session_stats.input_tokens += input_tokens
        self.session_stats.output_tokens += output_tokens
        if self.runtime is not None:
            self.runtime.writer.append_usage(input_tokens, output_tokens)
        self.refresh_status()

    async def action_compact(self) -> None:
        if self.state is not SessionState.IDLE:
            return
        if self.runtime is None:
            await self.append_timeline(notice_entry("当前没有可压缩的会话"))
            return
        self.state = SessionState.COMPACTING
        self.refresh_status()
        stable = self._stable_prompt()
        result = await self.runtime.context.compact_now(
            self.conv,
            stable,
            self.current_definitions(),
            self.skill_environment(
                (
                    await asyncio.to_thread(
                        gather_environment,
                        self.version,
                        self.provider_for_skill(
                            self.skill_runtime.requested_model()
                        ).model,
                    )
                ).render()
            ),
        )
        await self.append_timeline(notice_entry(result))
        self.runtime.writer.append_visible("notice", result)
        self.state = SessionState.IDLE
        self.refresh_status()

    async def action_resume(self) -> None:
        if self.state is not SessionState.IDLE:
            await self.append_timeline(notice_entry("请等待当前任务完成"))
            return
        self.session_repository.cleanup_expired()
        sessions = self.session_repository.list_sessions()
        if not sessions:
            await self.append_timeline(notice_entry("没有可恢复的会话"))
            return
        self.state = SessionState.RESUMING
        from .resume import ResumeScreen

        self.push_screen(
            ResumeScreen(sessions, self._delete_session), self._resume_selected
        )

    def _delete_session(self, summary: object) -> bool:
        session_id = getattr(summary, "session_id", "")
        is_current = (
            self.runtime is not None and self.runtime.paths.session_id == session_id
        )
        if not is_current:
            return self.session_repository.delete(session_id)

        # Windows 不允许删除仍由 Writer 打开的 JSONL；先关闭，失败时立即恢复。
        self.runtime.close()
        deleted = self.session_repository.delete(session_id)
        if deleted:
            self.runtime = None
            self.conv = Conversation()
            self.session_stats = SessionStats()
            self.skill_runtime.clear()
            return True
        if self.provider is not None and self.provider_config is not None:
            archive = self.session_repository.restore(session_id)
            self.runtime = SessionRuntime.restore(
                self.root,
                session_id,
                self.provider,
                self.provider_config.context_window,
                archive,
                stale=False,
                enable_title=self.session_enabled,
            )
            self.runtime.context.set_hook_dispatcher(self.dispatch_hook)
            self.conv = self.runtime.conversation
            self.session_stats = archive.stats
        return False

    def _resume_selected(self, summary: object) -> None:
        asyncio.create_task(self._finish_resume(summary))

    async def _finish_resume(self, summary: object) -> None:
        try:
            if summary is None or self.provider is None or self.provider_config is None:
                return
            self.skill_runtime.clear()
            session_id = getattr(summary, "session_id", "")
            archive = self.session_repository.restore(session_id)
            stale = (
                archive.last_active is not None
                and datetime.now() - archive.last_active > timedelta(days=7)
            )
            if self.runtime is not None:
                await self._close_runtime()
            self.runtime = SessionRuntime.restore(
                self.root,
                session_id,
                self.provider,
                self.provider_config.context_window,
                archive,
                stale=stale,
                enable_title=self.session_enabled,
            )
            self.runtime.context.set_hook_dispatcher(self.dispatch_hook)
            self.conv = self.runtime.conversation
            self.session_stats = archive.stats
            await self._replay(archive.visible_events)
            await self.append_timeline(
                notice_entry(
                    f"已恢复会话 {session_id}，共 {len(archive.messages)} 条消息"
                )
            )
            await self.dispatch_hook(HookEvent.SESSION_RESUME, {})
        finally:
            self.state = SessionState.IDLE
            self.refresh_status()

    async def _replay(self, events: list[object]) -> None:
        timeline = self.query_one("#timeline", Timeline)
        await timeline.clear()
        calls: dict[str, ToolRun] = {}
        for event in events:
            event_type = getattr(event, "type", "")
            data = getattr(event, "data", {})
            if event_type == "message" and isinstance(data, dict):
                role = data.get("role")
                if role == "user":
                    await timeline.append(user_entry(str(data.get("content", ""))))
                elif role == "assistant":
                    content = str(data.get("content", ""))
                    if content:
                        from .view import assistant_entry

                        await timeline.append(assistant_entry(content, 0))
                    for call in data.get("tool_calls", []):
                        if isinstance(call, dict):
                            calls[str(call.get("id", ""))] = ToolRun(
                                str(call.get("name", "tool")),
                                str(call.get("input", "{}")),
                            )
                elif role == "tool":
                    for result in data.get("tool_results", []):
                        if isinstance(result, dict):
                            from .view import tool_result_entry

                            run = calls.get(
                                str(result.get("tool_call_id", "")),
                                ToolRun("tool", "{}"),
                            )
                            await timeline.append(
                                tool_result_entry(
                                    run.name,
                                    run.args,
                                    str(result.get("content", "")),
                                    bool(result.get("is_error", False)),
                                )
                            )
            elif event_type == "notice" and isinstance(data, dict):
                await timeline.append(notice_entry(str(data.get("text", ""))))
            elif event_type == "error" and isinstance(data, dict):
                await timeline.append(notice_entry(f"错误: {data.get('text', '')}"))

    def _stable_prompt(self) -> str:
        from mewcode.prompt import build_system_prompt

        return build_system_prompt(
            self.instructions.content,
            self.memory_manager.prompt_index(),
            self.skill_runtime.available_prompt(),
        )

    async def append_timeline(self, entry: Widget) -> None:
        await self.query_one("#timeline", Timeline).append(entry)

    async def action_quit(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
        if self.runtime is not None:
            await self._close_runtime()
        self.skill_runtime.clear()
        self.exit()

    def action_cancel_or_quit(self) -> None:
        if self.state in (
            SessionState.STREAMING,
            SessionState.APPROVING,
            SessionState.FORKING,
        ):
            self.action_cancel_turn()
            return
        asyncio.create_task(self.action_quit())

    def action_cancel_turn(self) -> None:
        if self.state is SessionState.APPROVING and self.pending is not None:
            if not self.pending.respond.done():
                self.pending.respond.set_result(Outcome.DENY_ONCE)
            self.pending = None
        if (
            self.state
            in (SessionState.STREAMING, SessionState.APPROVING, SessionState.FORKING)
            and self.turn_cancel is not None
        ):
            self.turn_cancel.set()

    async def action_cycle_permission_mode(self) -> None:
        if self.state is not SessionState.IDLE:
            return
        self.mode = Mode((int(self.mode) + 1) % len(Mode))
        await self.append_timeline(notice_entry(f"权限模式已切换为 {self.mode}"))
        self.refresh_status()

    def on_key(self, event: events.Key) -> None:
        if self.state is not SessionState.APPROVING:
            return
        if event.key in {"up", "k"}:
            self.approve_cursor = (self.approve_cursor - 1) % 4
        elif event.key in {"down", "j"}:
            self.approve_cursor = (self.approve_cursor + 1) % 4
        elif event.key in {"enter", "1", "2", "3", "4", "y", "n", "d"}:
            index = {
                "1": 0,
                "2": 1,
                "3": 2,
                "4": 3,
                "y": 0,
                "n": 3,
                "d": 3,
            }.get(event.key, self.approve_cursor)
            self.resolve_approval(index)
        else:
            return
        event.prevent_default()
        from .stream import refresh_approval_view

        refresh_approval_view(self)

    def resolve_approval(self, index: int) -> None:
        if self.pending is None:
            return
        outcome = (
            Outcome.ALLOW_ONCE,
            Outcome.ALLOW_SESSION,
            Outcome.ALLOW_FOREVER,
            Outcome.DENY_ONCE,
        )[index]
        pending = self.pending
        self.pending = None
        self.state = SessionState.STREAMING
        if not pending.respond.done():
            pending.respond.set_result(outcome)

    def refresh_status(self) -> None:
        if self.provider is None:
            return
        try:
            self.query_one("#statusbar", Static).update(
                status_bar(
                    self.provider.model,
                    self.mode,
                    self.usage_in,
                    self.usage_out,
                )
            )
        except NoMatches:
            return

    def watch_state(self, state: SessionState) -> None:
        try:
            input_area = self.query_one("#input", TextArea)
        except Exception:
            return
        input_area.read_only = state is not SessionState.IDLE


class _AppForkExecutor:
    def __init__(self, app: MewCodeApp) -> None:
        self._app = app

    async def run(self, skill: ActiveSkill) -> str:
        return await self._app.run_fork_skill(skill)
