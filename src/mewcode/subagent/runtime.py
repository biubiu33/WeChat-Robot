"""Isolated child-agent runtime construction and execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from mewcode.agent import Agent, ApprovalRequest, Completion, Usage
from mewcode.conversation import Conversation
from mewcode.hook import HookContext, HookEngine, HookSessionState
from mewcode.llm import Message, Provider, ToolCall, ToolResult
from mewcode.permission import Engine, Mode
from mewcode.prompt import build_system_prompt
from mewcode.tool import Registry

from .cache import FileReadCache
from .catalog import AgentCatalog
from .model import (
    Definition,
    DefinitionSource,
    LaunchRequest,
    PermissionMode,
    TokenUsage,
)
from .policy import ScopedRegistry, allowed_tools


FORK_NAME = "fork"


class SubAgentError(ValueError):
    pass


class ModelUnavailableError(SubAgentError):
    pass


@dataclass(frozen=True)
class ParentContext:
    conversation: Conversation
    provider: Provider
    engine: Engine
    registry: Registry
    root: Path
    providers: Mapping[str, Provider]
    hook_engine: HookEngine | None = None
    version: str = ""
    allowed_tools: Collection[str] | None = None
    stable_system: str = ""
    approval_handler: Callable[[str, ApprovalRequest], Awaitable[None] | None] | None = None


@dataclass
class ChildRuntime:
    agent: Agent
    conversation: Conversation
    engine: Engine
    registry: ScopedRegistry
    hook_state: HookSessionState
    usage: TokenUsage
    cache: FileReadCache
    definition: Definition
    forked: bool
    mode: Mode
    provider: Provider


class SubAgentHost:
    """Create all child runtime variants through the same isolation boundary."""

    def __init__(self, catalog: AgentCatalog | None = None) -> None:
        self._catalog = catalog

    def prepare(self, request: LaunchRequest, parent: ParentContext) -> ChildRuntime:
        forked = not bool(request.subagent_type and request.subagent_type.strip())
        definition = self._definition_for(request, forked)
        provider = self._provider_for(request, definition, parent)
        return self._create_runtime(
            definition,
            parent,
            provider,
            forked=forked,
            task=request.prompt,
            background=forked or request.run_in_background,
            environment_prefix="",
        )

    def prepare_skill(
        self,
        name: str,
        instruction: str,
        tools: frozenset[str],
        parent: ParentContext,
        mode: Mode = Mode.DEFAULT,
    ) -> ChildRuntime:
        definition = Definition(
            name=f"skill-{name}",
            description=f"Skill {name}",
            instruction=instruction,
            tools=tools,
            disallowed_tools=frozenset(),
            model_profile=None,
            max_turns=25,
            permission_mode=_definition_permission_mode(mode),
            background=False,
            source=DefinitionSource.BUILTIN,
            path=Path(),
        )
        return self._create_runtime(
            definition,
            parent,
            parent.provider,
            forked=False,
            task="",
            background=False,
            environment_prefix=f"# 已激活 Skill\n\n## {name}\n{instruction}",
        )

    def _create_runtime(
        self,
        definition: Definition,
        parent: ParentContext,
        provider: Provider,
        *,
        forked: bool,
        task: str,
        background: bool,
        environment_prefix: str,
    ) -> ChildRuntime:
        mode = _permission_mode(definition.permission_mode)
        engine = parent.engine.fork_for_subagent(mode)
        cache = FileReadCache()
        permitted = allowed_tools(
            parent.registry,
            definition,
            background=background,
            parent_allowed=parent.allowed_tools,
        )
        overrides = {}
        load_skill = parent.registry.get("load_skill")
        if "load_skill" in permitted and callable(getattr(load_skill, "child_copy", None)):
            overrides["load_skill"] = load_skill.child_copy(
                frozenset(
                    name
                    for name in parent.registry.ordinary_names()
                    if name in permitted
                )
            )
        scoped = ScopedRegistry(
            parent.registry,
            permitted,
            cache=cache,
            path_resolver=engine.resolve_file_target,
            overrides=overrides,
        )
        conversation = (
            Conversation(build_forked_messages(parent.conversation, task))
            if forked
            else Conversation()
        )
        usage = TokenUsage()
        hook_state = HookSessionState()

        async def observe(item: Usage) -> None:
            usage.add(item.input, item.output, item.cache_write, item.cache_read)

        async def forward(approval: ApprovalRequest) -> None:
            if parent.approval_handler is None:
                return
            result = parent.approval_handler(definition.name, approval)
            if result is not None:
                await result

        stable_system = (
            parent.stable_system or build_system_prompt()
            if forked
            else build_system_prompt(definition.instruction)
        )
        agent = Agent(
            provider,
            scoped,  # type: ignore[arg-type]
            version=parent.version,
            engine=engine,
            hook_engine=parent.hook_engine,
            hook_state=hook_state,
            hook_context_supplier=lambda event, payload: HookContext(
                event,
                {
                    "event": event.value,
                    "cwd": str(parent.root),
                    "mode": str(mode),
                    "subagent": definition.name,
                    **payload,
                },
            ),
            max_turns=definition.max_turns,
            stable_system=stable_system,
            environment_supplier=(
                lambda environment: (
                    f"{environment_prefix}\n\n{environment}"
                    if environment_prefix
                    else environment
                )
            ),
            approval_forwarder=forward,
            usage_observer=observe,
        )
        return ChildRuntime(
            agent=agent,
            conversation=conversation,
            engine=engine,
            registry=scoped,
            hook_state=hook_state,
            usage=usage,
            cache=cache,
            definition=definition,
            forked=forked,
            mode=mode,
            provider=provider,
        )

    async def run_inline(
        self,
        runtime: ChildRuntime,
        task: str,
        cancel: asyncio.Event | None = None,
    ) -> Completion:
        return await runtime.agent.run_to_completion(
            runtime.conversation, task, runtime.mode, cancel
        )

    def _definition_for(self, request: LaunchRequest, forked: bool) -> Definition:
        if forked:
            return _fork_definition(request.model_profile)
        assert request.subagent_type is not None
        if self._catalog is None:
            raise SubAgentError("No agent catalog is configured")
        definition = self._catalog.resolve(request.subagent_type)
        if definition is None:
            raise SubAgentError(f"Unknown subagent type: {request.subagent_type}")
        return definition

    @staticmethod
    def _provider_for(
        request: LaunchRequest, definition: Definition, parent: ParentContext
    ) -> Provider:
        profile = (
            request.model_profile
            if request.model_profile is not None
            else definition.model_profile
        )
        if profile is None or profile == "inherit":
            return parent.provider
        provider = parent.providers.get(profile)
        if provider is None:
            raise ModelUnavailableError(f"Configured model profile is unavailable: {profile}")
        return provider


def fork_boilerplate(task: str) -> str:
    return (
        "<fork_boilerplate>\n"
        "You are an isolated sub-agent. Complete the task autonomously. "
        "Do not ask the user questions, wait for replies, or delegate work to another agent. "
        "Use only the tools exposed to you and return a concise final result.\n\n"
        f"Task:\n{task}\n"
        "</fork_boilerplate>"
    )


def build_forked_messages(parent: Conversation, task: str) -> list[Message]:
    """Deep-copy parent messages and complete dangling tool calls before Forking."""

    copied: list[Message] = []
    pending: dict[str, ToolCall] = {}
    for message in parent.messages():
        if pending and message.role != "tool":
            copied.append(_missing_results(pending))
            pending.clear()
        clone = Message(
            role=message.role,
            content=message.content,
            tool_calls=[ToolCall(call.id, call.name, call.input) for call in message.tool_calls],
            tool_results=[
                ToolResult(result.tool_call_id, result.content, result.is_error)
                for result in message.tool_results
            ],
        )
        copied.append(clone)
        if clone.role == "assistant" and clone.tool_calls:
            pending = {call.id: call for call in clone.tool_calls}
        elif clone.role == "tool":
            for result in clone.tool_results:
                pending.pop(result.tool_call_id, None)
    if pending:
        copied.append(_missing_results(pending))
    copied.append(Message(role="user", content=fork_boilerplate(task)))
    return copied


def _missing_results(calls: Mapping[str, ToolCall]) -> Message:
    return Message(
        role="tool",
        tool_results=[
            ToolResult(
                call_id,
                "Tool call was not completed before this sub-agent Fork.",
                is_error=True,
            )
            for call_id in calls
        ],
    )


def _fork_definition(model_profile: str | None) -> Definition:
    return Definition(
        name=FORK_NAME,
        description="Forked parent context",
        instruction="",
        tools=None,
        disallowed_tools=frozenset(),
        model_profile=model_profile,
        max_turns=25,
        permission_mode=PermissionMode.DEFAULT,
        background=True,
        source=DefinitionSource.BUILTIN,
        path=Path(),
    )


def _permission_mode(value: PermissionMode) -> Mode:
    return {
        PermissionMode.DEFAULT: Mode.DEFAULT,
        PermissionMode.ACCEPT_EDITS: Mode.ACCEPT_EDITS,
        PermissionMode.PLAN: Mode.PLAN,
        PermissionMode.BYPASS: Mode.BYPASS,
        PermissionMode.DONT_ASK: Mode.DONT_ASK,
    }[value]


def _definition_permission_mode(mode: Mode) -> PermissionMode:
    return {
        Mode.DEFAULT: PermissionMode.DEFAULT,
        Mode.ACCEPT_EDITS: PermissionMode.ACCEPT_EDITS,
        Mode.PLAN: PermissionMode.PLAN,
        Mode.BYPASS: PermissionMode.BYPASS,
        Mode.DONT_ASK: PermissionMode.DONT_ASK,
    }[mode]


__all__ = [
    "ChildRuntime",
    "FORK_NAME",
    "ModelUnavailableError",
    "ParentContext",
    "SubAgentError",
    "SubAgentHost",
    "build_forked_messages",
    "fork_boilerplate",
]
