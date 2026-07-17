from __future__ import annotations

import asyncio
from datetime import datetime

from textual.app import App

from mewcode.session.repository import SessionSummary
from mewcode.tui.resume import ResumeScreen


class ResumeHost(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.selected: SessionSummary | None = None
        self.deleted: list[str] = []
        self.sessions = [
            SessionSummary(
                "20260717-120000-a1b2", "第一会话", datetime.now(), 1, "demo", 10
            ),
            SessionSummary(
                "20260717-120001-c3d4", "第二会话", datetime.now(), 2, "demo", 20
            ),
        ]

    async def on_mount(self) -> None:
        self.push_screen(ResumeScreen(self.sessions, self._delete), self._selected)

    def _delete(self, session: SessionSummary) -> bool:
        self.deleted.append(session.session_id)
        return True

    def _selected(self, session: SessionSummary | None) -> None:
        self.selected = session


def test_resume_screen_keyboard_selects_and_x_deletes() -> None:
    async def run() -> None:
        app = ResumeHost()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert app.selected is not None
            assert app.selected.session_id == "20260717-120001-c3d4"

        app = ResumeHost()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#delete-20260717-120000-a1b2")
            await pilot.pause()
            assert app.deleted == ["20260717-120000-a1b2"]

    asyncio.run(run())
