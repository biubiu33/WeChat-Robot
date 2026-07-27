from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.hook import (
    Action,
    Condition,
    ConditionGroup,
    Hook,
    HookCatalog,
    HookContext,
    HookEngine,
    HookEvent,
    HookSessionState,
)
from mewcode.permission.rule import Pattern


def run(coro):
    return asyncio.run(coro)


def test_conditions_and_prompts_follow_declaration_order() -> None:
    catalog = HookCatalog(
        (
            Hook(
                "first",
                HookEvent.PRE_USER_MESSAGE,
                ConditionGroup(
                    "all_of", (Condition("prompt", Pattern("exact", "hello")),)
                ),
                Action("prompt", text="one"),
            ),
            Hook(
                "second",
                HookEvent.PRE_USER_MESSAGE,
                ConditionGroup(
                    "any_of", (Condition("missing.path", Pattern("exact", "")),)
                ),
                Action("prompt", text="two"),
            ),
        )
    )
    engine = HookEngine(catalog)
    state = HookSessionState()

    dispatch = run(
        engine.dispatch(
            HookEvent.PRE_USER_MESSAGE,
            HookContext(HookEvent.PRE_USER_MESSAGE, {"prompt": "hello"}),
            state,
        )
    )

    assert not dispatch.blocked
    assert engine.take_reminders(state) == ("one", "two")
    assert engine.take_reminders(state) == ()


def test_once_failure_retries_and_success_confirms(monkeypatch) -> None:
    hook = Hook(
        "once", HookEvent.STOP, None, Action("shell", command="ignored"), only_once=True
    )
    engine = HookEngine(HookCatalog((hook,)))
    state = HookSessionState()
    calls = 0

    async def fake_execute(*args, **kwargs):
        nonlocal calls
        calls += 1
        from mewcode.hook.model import ActionResult

        return ActionResult(calls > 1)

    monkeypatch.setattr("mewcode.hook.engine.execute_action", fake_execute)
    context = HookContext(HookEvent.STOP, {})

    run(engine.dispatch(HookEvent.STOP, context, state))
    run(engine.dispatch(HookEvent.STOP, context, state))
    run(engine.dispatch(HookEvent.STOP, context, state))

    assert calls == 2
    assert state.executed == {"once"}
    assert state.reserved == set()


def test_async_once_confirms_after_background_work(monkeypatch) -> None:
    hook = Hook(
        "async-once",
        HookEvent.POST_TOOL_USE,
        None,
        Action("shell", command="ignored"),
        only_once=True,
        asynchronous=True,
        source=Path("hooks.yaml"),
    )
    engine = HookEngine(HookCatalog((hook,)))
    state = HookSessionState()
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_execute(*args, **kwargs):
        started.set()
        await release.wait()
        from mewcode.hook.model import ActionResult

        return ActionResult(True)

    monkeypatch.setattr("mewcode.hook.engine.execute_action", fake_execute)

    async def scenario() -> None:
        context = HookContext(HookEvent.POST_TOOL_USE, {})
        await engine.dispatch(HookEvent.POST_TOOL_USE, context, state)
        await started.wait()
        assert state.reserved == {"async-once"}
        await engine.dispatch(HookEvent.POST_TOOL_USE, context, state)
        release.set()
        await asyncio.gather(*state.background_tasks)

    run(scenario())

    assert state.executed == {"async-once"}
