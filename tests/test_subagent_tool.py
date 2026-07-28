from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from mewcode.conversation import Conversation
from mewcode.llm import Request, StreamEvent
from mewcode.permission import new_engine
from mewcode.subagent import (
    AgentCatalog,
    AgentTool,
    Definition,
    DefinitionSource,
    ParentContext,
    PermissionMode,
    SubAgentHost,
    TaskGetTool,
    TaskListTool,
    TaskManager,
)
from mewcode.tool import Registry


class FakeProvider:
    name = "fake"

    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.model = "fake"
        self.scripts = scripts
        self.requests: list[Request] = []

    def redact(self, text: str) -> str:
        return text

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        for item in self.scripts[len(self.requests) - 1]:
            yield item


def setup(tmp_path: Path, provider: FakeProvider):
    definition = Definition(
        name="explore",
        description="read only",
        instruction="explore role instruction",
        tools=frozenset(),
        disallowed_tools=frozenset(),
        model_profile=None,
        max_turns=3,
        permission_mode=PermissionMode.DEFAULT,
        background=False,
        source=DefinitionSource.BUILTIN,
        path=Path("explore.md"),
    )
    catalog = AgentCatalog(tmp_path, tmp_path / "user", tmp_path / "builtin", {"explore": definition}, ())
    host = SubAgentHost(catalog)
    manager = TaskManager(host)
    engine, error = new_engine(tmp_path)
    assert error is None
    context = ParentContext(
        conversation=Conversation(),
        provider=provider,
        engine=engine,
        registry=Registry(),
        root=tmp_path,
        providers={},
    )
    return host, manager, context


async def wait_complete(manager: TaskManager, task_id: str):
    for _ in range(300):
        task = manager.get(task_id)
        assert task is not None
        if task.status.value != "running":
            return task
        await asyncio.sleep(0.01)
    raise AssertionError("task did not finish")


def test_agent_tool_uses_fixed_schema_and_returns_foreground_result(tmp_path: Path) -> None:
    provider = FakeProvider([[StreamEvent(text="explored"), StreamEvent(done=True)]])
    host, manager, context = setup(tmp_path, provider)
    tool = AgentTool(host, manager, lambda: context)

    result = asyncio.run(
        tool.execute(
            json.dumps(
                {
                    "prompt": "inspect",
                    "description": "inspect code",
                    "subagent_type": "EXPLORE",
                }
            )
        )
    )

    assert result.content == "explored"
    assert tool.parameters()["required"] == ["prompt", "description"]
    assert set(tool.parameters()["properties"]) == {
        "prompt",
        "description",
        "subagent_type",
        "model",
        "run_in_background",
        "name",
    }
    assert len(context.conversation) == 0
    assert "explore role instruction" in provider.requests[0].system.stable


def test_fork_is_always_background_and_is_queryable(tmp_path: Path) -> None:
    async def scenario() -> None:
        provider = FakeProvider([[StreamEvent(text="forked"), StreamEvent(done=True)]])
        host, manager, context = setup(tmp_path, provider)
        tool = AgentTool(host, manager, lambda: context)

        result = await tool.execute(
            json.dumps({"prompt": "continue", "description": "fork work"})
        )
        payload = json.loads(result.content)
        terminal = await wait_complete(manager, payload["task_id"])
        detail = await TaskGetTool(manager).execute(json.dumps({"task_id": terminal.id}))
        listed = await TaskListTool(manager).execute("{}")

        assert payload["background"] is True
        assert terminal.result == "forked", (terminal.status, terminal.error)
        assert json.loads(detail.content)["status"] == "completed"
        assert "task-notification" in manager.take_notifications()[0]
        assert json.loads(listed.content)[0]["task_id"] == terminal.id

    asyncio.run(scenario())


def test_background_disabled_forces_defined_foreground_and_rejects_fork(tmp_path: Path) -> None:
    provider = FakeProvider([[StreamEvent(text="defined"), StreamEvent(done=True)]])
    host, manager, context = setup(tmp_path, provider)
    tool = AgentTool(host, manager, lambda: context, enable_background=False)

    defined = asyncio.run(
        tool.execute(
            json.dumps(
                {
                    "prompt": "defined",
                    "description": "defined",
                    "subagent_type": "explore",
                    "run_in_background": True,
                }
            )
        )
    )
    fork = asyncio.run(
        tool.execute(json.dumps({"prompt": "fork", "description": "fork"}))
    )

    assert defined.content == "defined"
    assert fork.is_error and "background_disabled" in fork.content


def test_detaching_a_foreground_defined_task_reuses_the_running_child(tmp_path: Path) -> None:
    class HoldingProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__([])
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
            self.requests.append(request)
            self.started.set()
            await self.release.wait()
            yield StreamEvent(text="finished")
            yield StreamEvent(done=True)

    async def scenario() -> None:
        provider = HoldingProvider()
        host, manager, context = setup(tmp_path, provider)
        tool = AgentTool(host, manager, lambda: context)
        execution = asyncio.create_task(
            tool.execute(
                json.dumps(
                    {
                        "prompt": "inspect",
                        "description": "inspect code",
                        "subagent_type": "explore",
                        "name": "inspect",
                    }
                )
            )
        )
        await provider.started.wait()

        detached = tool.detach_foreground()
        assert detached is not None
        response = await execution
        payload = json.loads(response.content)

        assert payload["task_id"] == detached.id
        assert payload["status"] == "running"
        assert len(provider.requests) == 1

        provider.release.set()
        terminal = await wait_complete(manager, detached.id)
        assert terminal.result == "finished"
        assert len(provider.requests) == 1

    asyncio.run(scenario())


def test_agent_tool_reports_unknown_roles_and_invalid_flags(tmp_path: Path) -> None:
    provider = FakeProvider([])
    host, manager, context = setup(tmp_path, provider)
    tool = AgentTool(host, manager, lambda: context)

    unknown = asyncio.run(
        tool.execute(
            json.dumps(
                {"prompt": "task", "description": "task", "subagent_type": "missing"}
            )
        )
    )
    invalid = asyncio.run(
        tool.execute(
            json.dumps(
                {"prompt": "task", "description": "task", "run_in_background": "yes"}
            )
        )
    )

    assert unknown.is_error and "invalid_subagent" in unknown.content
    assert invalid.is_error and "invalid_arguments" in invalid.content
