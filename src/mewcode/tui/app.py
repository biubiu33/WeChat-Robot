from __future__ import annotations

import asyncio
import os
import time
from enum import Enum

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea

from mewcode import __version__
from mewcode.config import ProviderConfig
from mewcode.conversation import Conversation
from mewcode.llm import Provider, new_provider
from mewcode.prompt import render_banner
from mewcode.tool import Registry, new_default_registry

from .view import selecting_status, status_bar, user_block


class SessionState(Enum):
    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"


class PromptInput(TextArea):
    def on_key(self, event: events.Key) -> None:
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

    #log {
        height: 1fr;
        padding: 1 2;
    }

    #streaming {
        height: auto;
        max-height: 12;
        padding: 0 2;
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
    """

    BINDINGS = [("ctrl+c", "quit", "退出")]

    def __init__(
        self,
        providers: list[ProviderConfig],
        version: str = __version__,
        registry: Registry | None = None,
    ) -> None:
        super().__init__()
        self.providers = providers
        self.version = version
        self.registry = registry if registry is not None else new_default_registry()
        self.state = SessionState.SELECTING if len(providers) > 1 else SessionState.IDLE
        self.provider: Provider | None = None
        self.conv = Conversation()
        self.cur_reply = ""
        self.cur_tool: tuple[str, str] | None = None
        self.turn_start = 0.0
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None

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
            RichLog(id="log", wrap=True, markup=True),
            Static("", id="streaming"),
            PromptInput(placeholder="❯ Send a message...", id="input"),
            Static("", id="statusbar"),
            id="main",
        )

    async def on_mount(self) -> None:
        self.query_one("#log", RichLog).write(render_banner(self.version, os.getcwd()))

        if len(self.providers) == 1:
            self.provider = new_provider(self.providers[0])
            self.query_one("#selector").display = False
            self.query_one("#statusbar", Static).update(
                status_bar(self.provider.name, self.provider.model)
            )
            self.query_one("#input").focus()
        else:
            self.query_one("#main").display = False
            self.query_one("#statusbar", Static).update(selecting_status())
            provider_list = self.query_one("#provider-list", OptionList)
            provider_list.highlighted = 0
            provider_list.focus()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
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

        if self.provider is None:
            return

        self.conv.add_user(text)
        self.query_one("#log", RichLog).write(user_block(text))
        text_area.text = ""
        text_area.read_only = True
        self.cur_reply = ""
        self.turn_start = time.monotonic()
        self.state = SessionState.STREAMING

        from .stream import consume_stream, tick

        self._timer = self.set_interval(0.1, lambda: tick(self, SessionState.STREAMING))
        self._stream_task = asyncio.create_task(consume_stream(self))

    async def action_quit(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
        self.exit()

    def watch_state(self, state: SessionState) -> None:
        try:
            input_area = self.query_one("#input", TextArea)
        except Exception:
            return
        input_area.read_only = state is not SessionState.IDLE
