"""会话恢复选择屏。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, ListItem, ListView, Static

from mewcode.session.repository import SessionSummary


class SessionItem(ListItem):
    def __init__(self, session: SessionSummary) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Static(
                f"{self.session.title}\n{self.session.session_id} · "
                f"{_relative_time(self.session.last_active)} · "
                f"{self.session.message_count} 条 · "
                f"{self.session.model or 'unknown'} · {self.session.size_bytes} B",
                classes="resume-summary",
            ),
            Button(
                "X", id=f"delete-{self.session.session_id}", classes="delete-session"
            ),
            classes="resume-row",
        )


class ResumeScreen(ModalScreen[SessionSummary | None]):
    BINDINGS = [("escape", "cancel", "取消")]
    CSS = """
    #resume-dialog { width: 92%; height: 75%; padding: 1 2; background: $surface; }
    #resume-list { height: 1fr; margin-top: 1; }
    .resume-row { width: 1fr; height: auto; padding: 0 1; }
    .resume-summary { width: 1fr; }
    .delete-session { width: 3; min-width: 3; height: 3; margin: 0; }
    #resume-status { height: 1; color: $error; }
    """

    def __init__(
        self,
        sessions: list[SessionSummary],
        delete_session: Callable[[SessionSummary], bool],
    ) -> None:
        super().__init__()
        self._all = sessions
        self._filtered = list(sessions)
        self._delete_session = delete_session

    def compose(self) -> ComposeResult:
        yield Container(
            Static("恢复会话", classes="resume-title"),
            Input(placeholder="筛选会话...", id="resume-search"),
            ListView(*self._items(), id="resume-list"),
            Static("", id="resume-status"),
            id="resume-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#resume-search", Input).focus()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "resume-search":
            return
        needle = event.value.strip().lower()
        self._filtered = [
            session for session in self._all if needle in session.title.lower()
        ]
        await self._refresh_items()

    def on_key(self, event: events.Key) -> None:
        if event.key not in {"up", "down", "enter"}:
            return
        view = self.query_one("#resume-list", ListView)
        if event.key == "enter":
            item = view.highlighted_child
            if isinstance(item, SessionItem):
                event.stop()
                event.prevent_default()
                self.dismiss(item.session)
            return
        if not self._filtered:
            return
        current = view.index if view.index is not None else 0
        view.index = max(
            0, min(len(self._filtered) - 1, current + (-1 if event.key == "up" else 1))
        )
        view.focus()
        event.stop()
        event.prevent_default()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "resume-list" or not isinstance(
            event.item, SessionItem
        ):
            return
        event.stop()
        self.dismiss(event.item.session)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not event.button.id or not event.button.id.startswith("delete-"):
            return
        event.stop()
        session_id = event.button.id.removeprefix("delete-")
        session = next(
            (item for item in self._all if item.session_id == session_id), None
        )
        if session is None:
            return
        asyncio.create_task(self._delete_and_refresh(session))

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def _delete_and_refresh(self, session: SessionSummary) -> None:
        if not self._delete_session(session):
            self._set_status("删除失败，会话记录未移除")
            return
        self._all = [
            item for item in self._all if item.session_id != session.session_id
        ]
        self._filtered = [
            item for item in self._filtered if item.session_id != session.session_id
        ]
        await self._refresh_items()
        self._set_status("已删除会话及其工具缓存")

    async def _refresh_items(self) -> None:
        view = self.query_one("#resume-list", ListView)
        await view.remove_children()
        if self._filtered:
            await view.mount(*self._items())
            view.index = 0

    def _items(self) -> list[SessionItem]:
        return [SessionItem(session) for session in self._filtered]

    def _set_status(self, text: str) -> None:
        self.query_one("#resume-status", Static).update(text)


def _relative_time(value: datetime) -> str:
    seconds = max(0, int((datetime.now() - value).total_seconds()))
    if seconds < 3600:
        return f"{max(1, seconds // 60)} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"
