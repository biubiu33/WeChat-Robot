from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .actions import execute_action
from .config import load_catalog
from .model import (
    BLOCKING_EVENTS,
    ActionResult,
    Hook,
    HookCatalog,
    HookContext,
    HookDispatch,
    HookEvent,
    HookSessionState,
    HookSnapshot,
    HookSnapshotEntry,
)


class HookEngine:
    def __init__(self, catalog: HookCatalog = HookCatalog()) -> None:
        self.catalog = catalog

    @classmethod
    def load(cls, root: Path, home: Path | None = None) -> HookEngine:
        return cls(load_catalog(root, home))

    async def dispatch(
        self,
        event: HookEvent,
        context: HookContext,
        state: HookSessionState,
    ) -> HookDispatch:
        blocking = event in BLOCKING_EVENTS
        for hook in self.catalog.hooks:
            if hook.event is not event or not _matches(hook, context):
                continue
            if hook.only_once and (
                hook.name in state.reserved or hook.name in state.executed
            ):
                continue
            if hook.only_once:
                state.reserved.add(hook.name)
            if hook.asynchronous:
                task = asyncio.create_task(self._run_background(hook, context, state))
                state.background_tasks.add(task)
                task.add_done_callback(state.background_tasks.discard)
                continue
            result = await self._run(hook, context, state, blocking=blocking)
            if result.blocked:
                return HookDispatch(hook.name, result.reason)
        return HookDispatch()

    def take_reminders(self, state: HookSessionState) -> tuple[str, ...]:
        reminders = tuple(state.reminders)
        state.reminders.clear()
        return reminders

    def snapshot(self) -> HookSnapshot:
        return HookSnapshot(
            entries=tuple(
                HookSnapshotEntry(
                    hook.name,
                    hook.event,
                    hook.action.type,
                    hook.only_once,
                    hook.asynchronous,
                )
                for hook in self.catalog.hooks
            ),
            sources=self.catalog.sources,
        )

    async def close_session(self, state: HookSessionState) -> None:
        tasks = tuple(state.background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        state.background_tasks.clear()
        state.reserved.clear()
        state.reminders.clear()

    async def _run_background(
        self, hook: Hook, context: HookContext, state: HookSessionState
    ) -> None:
        try:
            await self._run(hook, context, state, blocking=False)
        except asyncio.CancelledError:
            raise

    async def _run(
        self,
        hook: Hook,
        context: HookContext,
        state: HookSessionState,
        *,
        blocking: bool,
    ) -> ActionResult:
        try:
            result = await execute_action(hook, context, state, blocking=blocking)
        except asyncio.CancelledError:
            self._release(hook, state)
            raise
        except Exception as exc:
            result = ActionResult(False, reason=f"{type(exc).__name__}: {exc}")
        if result.success:
            self._confirm(hook, state)
        else:
            self._release(hook, state)
            _warn(hook, context.event, result.reason)
        return result

    @staticmethod
    def _confirm(hook: Hook, state: HookSessionState) -> None:
        if hook.only_once:
            state.reserved.discard(hook.name)
            state.executed.add(hook.name)

    @staticmethod
    def _release(hook: Hook, state: HookSessionState) -> None:
        if hook.only_once:
            state.reserved.discard(hook.name)


def _matches(hook: Hook, context: HookContext) -> bool:
    group = hook.condition
    if group is None:
        return True
    values = []
    for condition in group.conditions:
        value = context.value(condition.field)
        text = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, sort_keys=True)
        )
        values.append(condition.match.matches(text, is_path=False))
    return all(values) if group.mode == "all_of" else any(values)


def _warn(hook: Hook, event: HookEvent, reason: str) -> None:
    print(f"[hook {hook.name}] {event.value} failed: {reason}", file=sys.stderr)
