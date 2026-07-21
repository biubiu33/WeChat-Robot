from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from mewcode.command import (
    Command,
    CommandConflictError,
    CommandDispatcher,
    CommandKind,
    CommandRegistry,
    InputKind,
    MemorySnapshot,
    SessionSnapshot,
    SkillSnapshot,
    SkillsSnapshot,
    StatusSnapshot,
    new_default_command_registry,
    new_skill_commands,
    parse_input,
)
from mewcode.permission import Mode
from mewcode.prompt import EXECUTE_DIRECTIVE


class FakeControl:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.mode = Mode.DEFAULT
        self.status = StatusSnapshot(
            "default",
            120,
            30,
            8,
            3,
            "demo-model",
            str(Path("workspace").resolve()),
        )
        self.memory = MemorySnapshot(("project_api.md",), ("user_style.md",))
        self.session: SessionSnapshot | None = SessionSnapshot(
            "20260720-120000-abcd", str(Path("session.jsonl").resolve())
        )
        self.skills = SkillsSnapshot(
            (SkillSnapshot("review-skill", "审查代码", "user", True),),
            ("broken.md: YAML 错误",),
        )

    async def show_message(self, text: str) -> None:
        self.events.append(("show", text))

    async def send_user_message(self, text: str) -> None:
        self.events.append(("send", text))

    async def compact_context(self) -> None:
        self.events.append(("compact", None))

    async def resume_session(self) -> None:
        self.events.append(("resume", None))

    async def clear_session(self) -> None:
        self.events.append(("clear", None))

    async def exit_app(self) -> None:
        self.events.append(("exit", None))

    def set_mode(self, mode: Mode) -> None:
        self.mode = mode
        self.status = StatusSnapshot(
            str(mode),
            self.status.input_tokens,
            self.status.output_tokens,
            self.status.tool_count,
            self.status.memory_count,
            self.status.model,
            self.status.working_directory,
        )
        self.events.append(("mode", mode))

    def refresh_status(self) -> None:
        self.events.append(("refresh", None))

    def status_snapshot(self) -> StatusSnapshot:
        return self.status

    def memory_snapshot(self) -> MemorySnapshot:
        return self.memory

    def session_snapshot(self) -> SessionSnapshot | None:
        return self.session

    def skills_snapshot(self) -> SkillsSnapshot:
        return self.skills

    async def run_skill(self, name: str, argument: str) -> None:
        self.events.append(("skill", (name, argument)))


async def noop_handler(context, argument: str) -> None:
    await context.control.show_message(argument)


def command(
    name: str,
    aliases: tuple[str, ...] = (),
    *,
    hidden: bool = False,
) -> Command:
    return Command(
        name,
        aliases,
        f"{name} description",
        f"/{name}",
        CommandKind.LOCAL,
        noop_handler,
        hidden=hidden,
    )


def dispatch(
    text: str,
    control: FakeControl | None = None,
    registry: CommandRegistry | None = None,
) -> FakeControl:
    active_control = control if control is not None else FakeControl()
    active_registry = (
        registry if registry is not None else new_default_command_registry()
    )
    asyncio.run(
        CommandDispatcher(active_registry).dispatch(
            parse_input(text),
            active_control,
        )
    )
    return active_control


def test_model_is_immutable_and_memory_total_is_derived() -> None:
    definition = command("demo")

    with pytest.raises(FrozenInstanceError):
        definition.name = "changed"  # type: ignore[misc]
    assert MemorySnapshot(("a.md", "b.md"), ("c.md",)).total == 3


def test_registry_normalizes_names_resolves_aliases_and_sorts_public() -> None:
    registry = CommandRegistry()
    registry.register(command("Zulu"))
    registry.register(command("Alpha", ("A",)))
    registry.register(command("hidden", hidden=True))

    assert registry.resolve("alpha") is registry.resolve("A")
    assert registry.resolve("ZULU") is not None
    assert [item.name for item in registry.public_commands()] == ["alpha", "zulu"]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (command("same"), command("SAME")),
        (command("one", ("alias",)), command("two", ("ALIAS",))),
        (command("one", ("two",)), command("two")),
        (command("one"), command("two", ("ONE",))),
    ],
)
def test_registry_rejects_all_cross_command_conflicts(
    first: Command, second: Command
) -> None:
    registry = CommandRegistry()
    registry.register(first)

    with pytest.raises(CommandConflictError, match="冲突"):
        registry.register(second)


def test_registry_rejects_internal_duplicate_and_invalid_keys() -> None:
    registry = CommandRegistry()

    with pytest.raises(CommandConflictError, match="重复"):
        registry.register(command("one", ("x", "X")))
    with pytest.raises(ValueError, match="不能为空"):
        registry.register(command(" "))
    with pytest.raises(ValueError, match="空白"):
        registry.register(command("bad name"))


def test_registry_completion_matches_alias_deduplicates_and_hides() -> None:
    registry = new_default_command_registry()
    registry.register(command("hidden-command", ("hc",), hidden=True))

    assert [item.name for item in registry.completions("h")] == ["help"]
    assert [item.name for item in registry.completions("c")] == ["clear", "compact"]
    assert registry.completions("hc") == ()
    assert [item.name for item in registry.completions("")] == sorted(
        item.name for item in registry.public_commands()
    )


@pytest.mark.parametrize(
    ("text", "kind", "message", "name", "argument"),
    [
        ("", InputKind.EMPTY, "", "", ""),
        ("   ", InputKind.EMPTY, "", "", ""),
        (" hello world ", InputKind.MESSAGE, "hello world", "", ""),
        ("/HeLp   clear  ", InputKind.COMMAND, "", "help", "clear"),
        ("/", InputKind.COMMAND, "", "", ""),
    ],
)
def test_parser_classifies_and_splits_input(
    text: str,
    kind: InputKind,
    message: str,
    name: str,
    argument: str,
) -> None:
    parsed = parse_input(text)

    assert (parsed.kind, parsed.text, parsed.command_name, parsed.argument) == (
        kind,
        message,
        name,
        argument,
    )


def test_dispatcher_rejects_non_command_inputs() -> None:
    dispatcher = CommandDispatcher(new_default_command_registry())

    with pytest.raises(ValueError, match="Slash"):
        asyncio.run(dispatcher.dispatch(parse_input("hello"), FakeControl()))


def test_dispatcher_reports_unknown_and_rejects_unexpected_arguments() -> None:
    unknown = dispatch("/missing")
    invalid = dispatch("/status extra")

    assert unknown.events == [("show", "未知命令 /missing。输入 /help 查看可用命令。")]
    assert invalid.events == [("show", "命令 /status 不接受参数。用法: /status")]


def test_default_registry_has_exact_public_commands_aliases_and_types() -> None:
    registry = new_default_command_registry()
    commands = {item.name: item for item in registry.public_commands()}

    assert set(commands) == {
        "exit",
        "plan",
        "do",
        "compact",
        "resume",
        "clear",
        "help",
        "status",
        "memory",
        "permission",
        "session",
        "skill",
    }
    assert commands["help"].aliases == ("h",)
    assert commands["clear"].aliases == ("c",)
    assert all(
        not item.aliases
        for name, item in commands.items()
        if name not in {"help", "clear"}
    )
    assert {item.kind for item in commands.values()} == set(CommandKind)
    assert all(
        item.description and item.usage and not item.hidden
        for item in commands.values()
    )


def test_local_help_lists_canonical_names_sorted_in_two_columns() -> None:
    control = dispatch("/help")
    output = str(control.events[0][1])
    lines = output.splitlines()

    names = [line.split()[0] for line in lines]
    assert names == sorted(names)
    assert len(lines) == 12
    assert "/h" not in names and "/c" not in names
    assert all("  " in line for line in lines)


def test_local_help_resolves_alias_and_shows_all_metadata() -> None:
    by_name = dispatch("/help clear")
    by_alias = dispatch("/help c")

    assert by_name.events == by_alias.events
    output = str(by_name.events[0][1])
    for label in ("名称:", "别名:", "类型:", "描述:", "用法:", "参数:"):
        assert label in output
    assert "/clear" in output and "/c" in output


def test_local_help_rejects_multiple_arguments_and_unknown_target() -> None:
    multiple = dispatch("/help clear extra")
    missing = dispatch("/help missing")

    assert multiple.events == [("show", "用法: /help [命令名]")]
    assert "/help" in str(missing.events[0][1])


def test_local_status_memory_permission_and_session_use_snapshots() -> None:
    status = dispatch("/status")
    memory = dispatch("/memory")
    permission = dispatch("/permission")
    session = dispatch("/session")

    status_text = str(status.events[0][1])
    assert status_text.count("\n") == 5
    for value in ("default", "120", "30", "8", "3", "demo-model"):
        assert value in status_text
    assert "project_api.md" in str(memory.events[0][1])
    assert "user_style.md" in str(memory.events[0][1])
    assert permission.events == [("show", "default")]
    assert "20260720-120000-abcd" in str(session.events[0][1])


def test_local_memory_and_session_render_empty_states() -> None:
    control = FakeControl()
    control.memory = MemorySnapshot()
    control.session = None

    dispatch("/memory", control)
    dispatch("/session", control)

    assert "项目层:\n- 无\n用户层:\n- 无" == control.events[0][1]
    assert control.events[1] == ("show", "当前尚未创建会话")


def test_plan_and_do_use_required_order_and_prompt() -> None:
    control = FakeControl()

    dispatch("/plan", control)
    dispatch("/do", control)

    assert control.events == [
        ("mode", Mode.PLAN),
        ("refresh", None),
        ("show", "已进入计划模式（只允许只读工具）"),
        ("mode", Mode.DEFAULT),
        ("refresh", None),
        ("send", EXECUTE_DIRECTIVE),
    ]


def test_dynamic_review_skill_uses_the_skill_execution_path() -> None:
    registry = new_default_command_registry()
    registry.replace_dynamic((), new_skill_commands((("review", "审查代码"),)))
    control = dispatch("/review current change", registry=registry)

    assert control.events == [("skill", ("review", "current change"))]


@pytest.mark.parametrize(
    ("name", "event"),
    [
        ("exit", "exit"),
        ("compact", "compact"),
        ("resume", "resume"),
        ("clear", "clear"),
        ("c", "clear"),
    ],
)
def test_ui_commands_delegate_to_control(name: str, event: str) -> None:
    control = dispatch(f"/{name}")

    assert control.events == [(event, None)]


def test_skill_command_lists_metadata_without_sop_and_dynamic_commands_delegate() -> (
    None
):
    listed = dispatch("/skill")
    output = str(listed.events[0][1])
    assert "/review-skill" in output
    assert "[user] [已激活]" in output
    assert "YAML 错误" in output
    assert "完整 SOP" not in output

    registry = new_default_command_registry()
    registry.replace_dynamic((), new_skill_commands((("review-skill", "审查代码"),)))
    control = dispatch("/review-skill API", registry=registry)
    assert control.events == [("skill", ("review-skill", "API"))]


def test_dynamic_command_replacement_is_atomic_on_conflict() -> None:
    registry = new_default_command_registry()
    registry.replace_dynamic((), new_skill_commands((("custom", "自定义"),)))

    with pytest.raises(CommandConflictError):
        registry.replace_dynamic(("custom",), new_skill_commands((("help", "冲突"),)))

    assert registry.resolve("custom") is not None
    assert registry.resolve("help") is not None
