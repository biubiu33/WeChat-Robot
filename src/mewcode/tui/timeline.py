from __future__ import annotations

from dataclasses import dataclass

from textual.containers import VerticalScroll
from textual.widget import Widget

BOTTOM_TOLERANCE = 1


@dataclass(frozen=True)
class ToolRun:
    name: str
    args: str


class Timeline(VerticalScroll):
    """可追加独立条目的时间线，并在用户位于底部时自动跟随。"""

    def is_near_bottom(self) -> bool:
        return self.max_scroll_y - self.scroll_y <= BOTTOM_TOLERANCE

    async def append(self, entry: Widget) -> None:
        follow_tail = self.is_near_bottom()
        await self.mount(entry)
        if follow_tail:
            self.refresh(layout=True)
            await self.wait_for_refresh()
            self._follow_tail()

    async def clear(self) -> None:
        await self.remove_children()
        self.scroll_to(y=0, animate=False, force=True, immediate=True)

    def _follow_tail(self) -> None:
        self.scroll_to(
            y=self.max_scroll_y,
            animate=False,
            force=True,
            immediate=True,
        )
