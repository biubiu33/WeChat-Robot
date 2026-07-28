from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from mewcode.conversation import Conversation
from mewcode.hook import HookEngine
from mewcode.llm import Request, StreamEvent, ToolCall, Usage
from mewcode.permission import Outcome, new_engine
from mewcode.skill import LoadSkillTool, SkillCatalog, SkillRuntime
from mewcode.subagent import (
    AgentCatalog,
    Definition,
    DefinitionSource,
    LaunchRequest,
    ModelUnavailableError,
    ParentContext,
    PermissionMode,
    SubAgentHost,
    build_forked_messages,
)
from mewcode.tool import Registry, Result


class FakeProvider:
    def __init__(self, model: str, scripts: list[list[StreamEvent]]) -> None:
        self.name = model
        self.model = model
        self.scripts = scripts
        self.requests: list[Request] = []

    def redact(self, text: str) -> str:
        return text

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        for item in self.scripts[len(self.requests) - 1]:
            yield item


class WriteTool:
    read_only = False

    def __init__(self) -> None:
        self.calls = 0

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "write"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        self.calls += 1
        return Result("written")


def role(
    *,
    name: str = "explore",
    model: str | None = None,
    tools: frozenset[str] | None = None,
    permission_mode: PermissionMode = PermissionMode.DEFAULT,
) -> Definition:
    return Definition(
        name=name,
        description="test child",
        instruction="role instruction",
        tools=tools,
        disallowed_tools=frozenset(),
        model_profile=model,
        max_turns=4,
        permission_mode=permission_mode,
        background=False,
        source=DefinitionSource.BUILTIN,
        path=Path("role.md"),
    )


def host_for(tmp_path: Path, definition: Definition) -> SubAgentHost:
    catalog = AgentCatalog(tmp_path, tmp_path / "user", tmp_path / "builtin", {definition.name: definition}, ())
    return SubAgentHost(catalog)


def parent_context(
    tmp_path: Path,
    provider: FakeProvider,
    registry: Registry,
    **kwargs: Any,
) -> ParentContext:
    engine, error = new_engine(tmp_path)
    assert error is None
    profiles = kwargs.pop("providers", {"haiku": provider})
    return ParentContext(
        conversation=Conversation(),
        provider=provider,
        engine=engine,
        registry=registry,
        root=tmp_path,
        providers=profiles,
        hook_engine=HookEngine(),
        **kwargs,
    )


def test_definition_runtime_has_fresh_state_and_selected_provider(tmp_path: Path) -> None:
    parent_provider = FakeProvider("parent", [])
    child_provider = FakeProvider(
        "haiku", [[StreamEvent(text="done", usage=Usage(5, 2)), StreamEvent(done=True)]]
    )
    registry = Registry()
    context = parent_context(
        tmp_path,
        parent_provider,
        registry,
        providers={"haiku": child_provider},
    )
    context.conversation.add_user("parent-only message")

    runtime = host_for(tmp_path, role(model="haiku")).prepare(
        LaunchRequest("inspect files", "short task", subagent_type="EXPLORE"), context
    )
    result = asyncio.run(host_for(tmp_path, role(model="haiku")).run_inline(runtime, "inspect files"))

    assert result.text == "done"
    assert len(context.conversation) == 1
    assert runtime.provider is child_provider
    assert runtime.usage.input_tokens == 5
    assert runtime.hook_state is not context.hook_engine
    assert "role instruction" in child_provider.requests[0].system.stable


def test_calling_model_inherit_overrides_a_role_profile(tmp_path: Path) -> None:
    parent_provider = FakeProvider("parent", [])
    child_provider = FakeProvider("haiku", [])
    context = parent_context(
        tmp_path,
        parent_provider,
        Registry(),
        providers={"haiku": child_provider},
    )

    runtime = host_for(tmp_path, role(model="haiku")).prepare(
        LaunchRequest(
            "inspect files",
            "short task",
            subagent_type="explore",
            model_profile="inherit",
        ),
        context,
    )

    assert runtime.provider is parent_provider


def test_fork_history_is_deep_copied_completed_and_constrained(tmp_path: Path) -> None:
    parent = Conversation()
    parent.add_user("original task")
    parent.add_assistant_with_tool_calls("working", [ToolCall("pending", "read_file", "{}")])

    messages = build_forked_messages(parent, "finish independently")

    assert messages[-2].role == "tool"
    assert messages[-2].tool_results[0].tool_call_id == "pending"
    assert messages[-1].role == "user"
    assert "<fork_boilerplate>" in messages[-1].content
    messages[1].tool_calls.append(ToolCall("new", "read_file", "{}"))
    assert len(parent.messages()[1].tool_calls) == 1

    provider = FakeProvider("parent", [[StreamEvent(text="fork done"), StreamEvent(done=True)]])
    context = parent_context(tmp_path, provider, Registry())
    context = ParentContext(
        conversation=parent,
        provider=context.provider,
        engine=context.engine,
        registry=context.registry,
        root=context.root,
        providers=context.providers,
        stable_system="parent stable prompt",
    )
    runtime = host_for(tmp_path, role()).prepare(
        LaunchRequest("finish independently", "fork task"), context
    )

    assert runtime.forked is True
    assert runtime.conversation.messages()[-1].content == messages[-1].content
    assert runtime.registry.get("Agent") is None


def test_unavailable_configured_profile_fails_before_child_creation(tmp_path: Path) -> None:
    provider = FakeProvider("parent", [])
    context = parent_context(tmp_path, provider, Registry(), providers={})

    with pytest.raises(ModelUnavailableError, match="unavailable"):
        host_for(tmp_path, role(model="haiku")).prepare(
            LaunchRequest("task", "description", subagent_type="explore"), context
        )


def test_child_approval_is_forwarded_without_user_conversation(tmp_path: Path) -> None:
    call = ToolCall("write", "write_file", '{"path":"a.txt","content":"x"}')
    provider = FakeProvider(
        "parent",
        [
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="finished"), StreamEvent(done=True)],
        ],
    )
    registry = Registry()
    writer = WriteTool()
    registry.register(writer)
    approvals = []

    async def approve(name, request):
        approvals.append((name, request.name))
        request.respond.set_result(Outcome.ALLOW_ONCE)

    context = parent_context(
        tmp_path, provider, registry, approval_handler=approve
    )
    host = host_for(tmp_path, role(tools=frozenset({"write_file"})))
    runtime = host.prepare(
        LaunchRequest("write", "description", subagent_type="explore"), context
    )
    result = asyncio.run(host.run_inline(runtime, "write"))

    assert result.text == "finished"
    assert writer.calls == 1
    assert approvals == [("explore", "write_file")]


def test_child_load_skill_is_isolated_and_rejects_nested_forks(tmp_path: Path) -> None:
    project = tmp_path / "project"
    skills = tmp_path / "skills"
    builtin = tmp_path / "builtin"
    for name, mode in (("inline", "inline"), ("fork", "fork")):
        path = skills / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"name: {name}\n"
            "description: test skill\n"
            "allowed_tools: []\n"
            f"mode: {mode}\n"
            "fork_history: none\n"
            "---\n"
            f"{name} instruction\n",
            encoding="utf-8",
        )
    skill_runtime = SkillRuntime(SkillCatalog.load(project, skills, builtin))
    registry = Registry()
    registry.register(LoadSkillTool(skill_runtime))
    provider = FakeProvider("parent", [])
    context = parent_context(tmp_path, provider, registry)
    host = host_for(tmp_path, role(tools=frozenset({"load_skill"})))
    runtime = host.prepare(
        LaunchRequest("task", "description", subagent_type="explore"), context
    )

    inline = asyncio.run(
        runtime.registry.execute("load_skill", '{"name":"inline"}')
    )
    fork = asyncio.run(runtime.registry.execute("load_skill", '{"name":"fork"}'))

    assert inline.content == "inline instruction"
    assert fork.is_error and "nested_agent_denied" in fork.content
    assert skill_runtime.active_skills() == ()
