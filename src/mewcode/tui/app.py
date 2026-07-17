from __future__ import annotations

import asyncio
import os
import time
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
from mewcode.config import ProviderConfig
from mewcode.conversation import Conversation
from mewcode.llm import Provider, new_provider
from mewcode.memory import InstructionBundle, MemoryManager
from mewcode.permission import Engine, Mode, Outcome, new_engine
from mewcode.prompt import render_banner
from mewcode.session.repository import SessionRepository
from mewcode.session.runtime import SessionRuntime
from mewcode.tool import Registry, new_default_registry

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
    COMPACTING = "compacting"
    RESUMING = "resuming"


class PromptInput(TextArea):
    def on_key(self, event: events.Key) -> None:
        if event.key == "shift+tab":
            app = self.app
            if hasattr(app, "action_cycle_permission_mode"):
                asyncio.create_task(app.action_cycle_permission_mode())
            event.prevent_default()
            event.stop()
            return

        if event.key in {"alt+enter", "meta+enter"}:
            self.insert("\n")
            event.prevent_default()
            return

        if event.key == "enter":
            app = self.app
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
        engine: Engine | None = None,
        root: Path | None = None,
        instructions: InstructionBundle | None = None,
        memory_manager: MemoryManager | None = None,
        session_repository: SessionRepository | None = None,
    ) -> None:
        super().__init__()
        self.providers = providers
        self.version = version
        self.registry = registry if registry is not None else new_default_registry()
        self.engine = engine if engine is not None else new_engine(os.getcwd())[0]
        self.root = (Path.cwd() if root is None else root).resolve()
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
        self.usage_in = 0
        self.usage_out = 0
        self.cur_reply = ""
        self.cur_tools: list[ToolRun] = []
        self.turn_start = 0.0
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None
        self.turn_cancel: asyncio.Event | None = None
        self.pending: ApprovalRequest | None = None
        self.approve_cursor = 0

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
        if event.option_list.id != "provider-list":
            return
        from .select import select_provider

        select_provider(self, event.option_index, SessionState.IDLE)

    async def submit_current_input(self) -> None:
        if self.state is not SessionState.IDLE:
            return

        text_area = self.query_one("#input", TextArea)
        text = text_area.text.strip()
        if not text:
            return

        if text == "/exit":
            await self.action_quit()
            return

        if text == "/resume":
            await self.action_resume()
            text_area.text = ""
            return

        if text == "/compact":
            text_area.text = ""
            await self.action_compact()
            return

        if text == "/plan":
            self.mode = Mode.PLAN
            await self.append_timeline(notice_entry("已进入计划模式（只允许只读工具）"))
            text_area.text = ""
            self.refresh_status()
            text_area.focus()
            return

        if self.provider is None:
            return

        if text == "/do":
            from mewcode.prompt import EXECUTE_DIRECTIVE

            self.mode = Mode.DEFAULT
            text = EXECUTE_DIRECTIVE

        self._ensure_runtime()
        self.conv.add_user(text)
        await self.append_timeline(user_entry(text))
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

    def activate_provider(self, cfg: ProviderConfig) -> None:
        self.provider = new_provider(cfg)
        self.provider_config = cfg
        if self.runtime is not None:
            self.runtime.close()
        self.runtime = None
        self.conv = Conversation()

    def _ensure_runtime(self) -> None:
        if self.runtime is not None:
            return
        if self.provider is None or self.provider_config is None:
            raise RuntimeError("尚未选择 Provider")
        self.runtime = SessionRuntime.new(
            self.root,
            self.provider,
            self.provider_config.context_window,
            enable_title=self.session_enabled,
        )
        self.conv = self.runtime.conversation

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
            self.conv, stable, self.registry.definitions()
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
            self.conv = self.runtime.conversation
        return False

    def _resume_selected(self, summary: object) -> None:
        asyncio.create_task(self._finish_resume(summary))

    async def _finish_resume(self, summary: object) -> None:
        try:
            if summary is None or self.provider is None or self.provider_config is None:
                return
            session_id = getattr(summary, "session_id", "")
            archive = self.session_repository.restore(session_id)
            stale = (
                archive.last_active is not None
                and datetime.now() - archive.last_active > timedelta(days=7)
            )
            if self.runtime is not None:
                self.runtime.close()
            self.runtime = SessionRuntime.restore(
                self.root,
                session_id,
                self.provider,
                self.provider_config.context_window,
                archive,
                stale=stale,
                enable_title=self.session_enabled,
            )
            self.conv = self.runtime.conversation
            await self._replay(archive.visible_events)
            await self.append_timeline(
                notice_entry(
                    f"已恢复会话 {session_id}，共 {len(archive.messages)} 条消息"
                )
            )
        finally:
            self.state = SessionState.IDLE
            self.refresh_status()

    async def _replay(self, events: list[object]) -> None:
        timeline = self.query_one("#timeline", Timeline)
        await timeline.remove_children()
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
            self.instructions.content, self.memory_manager.prompt_index()
        )

    async def append_timeline(self, entry: Widget) -> None:
        await self.query_one("#timeline", Timeline).append(entry)

    async def action_quit(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
        if self.runtime is not None:
            self.runtime.close()
        self.exit()

    def action_cancel_or_quit(self) -> None:
        if self.state in (SessionState.STREAMING, SessionState.APPROVING):
            self.action_cancel_turn()
            return
        self.exit()

    def action_cancel_turn(self) -> None:
        if self.state is SessionState.APPROVING and self.pending is not None:
            if not self.pending.respond.done():
                self.pending.respond.set_result(Outcome.DENY_ONCE)
            self.pending = None
        if (
            self.state in (SessionState.STREAMING, SessionState.APPROVING)
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
