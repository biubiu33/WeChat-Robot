from __future__ import annotations

from typing import TYPE_CHECKING

from mewcode.llm import new_provider

if TYPE_CHECKING:
    from .app import MewCodeApp, SessionState


def option_labels(app: MewCodeApp) -> list[str]:
    return [f"{provider.name} ({provider.model})" for provider in app.providers]


def select_provider(app: MewCodeApp, index: int, idle_state: SessionState) -> None:
    cfg = app.providers[index]
    app.provider = new_provider(cfg)
    app.state = idle_state
    app.query_one("#selector").display = False
    app.query_one("#main").display = True
    app.refresh_status()
    app.query_one("#input").focus()
