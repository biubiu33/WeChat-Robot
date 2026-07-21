from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from functools import wraps
from io import StringIO
from pathlib import Path
from typing import Any, TypeVar

from rich.console import Console

from mewcode.config import ProviderConfig
from mewcode.llm import Message, Request, StreamEvent, Usage
from mewcode.memory import MemoryManager
from mewcode.permission import Mode
from mewcode.prompt import EXECUTE_DIRECTIVE
from mewcode.session.archive import ArchiveWriter
from mewcode.session.paths import paths_for
from mewcode.session.repository import SessionRepository
from mewcode.skill import SkillCatalog, SkillRuntime
from mewcode.tool import new_default_registry
from mewcode.tui.app import MewCodeApp, SessionState
from mewcode.tui.completion import CommandCompletionMenu

F = TypeVar("F", bound=Callable[..., Any])


def async_test(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(func(*args, **kwargs))

    return wrapper  # type: ignore[return-value]


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.requests: list[Request] = []

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        yield StreamEvent(text=f"回复 {len(self.requests)}")
        yield StreamEvent(usage=Usage(10, 5))
        yield StreamEvent(done=True)


def config() -> ProviderConfig:
    return ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="test-key",
        model="fake-model",
    )


def app_for(
    root: Path,
    *,
    home: Path | None = None,
) -> tuple[MewCodeApp, FakeProvider]:
    provider = FakeProvider()
    app = MewCodeApp(
        [config()],
        registry=new_default_registry(),
        root=root,
        memory_manager=MemoryManager(root, home),
        session_repository=SessionRepository(root),
    )
    app.memory_enabled = False
    app.session_enabled = False
    return app, provider


def write_skill(
    root: Path,
    name: str,
    *,
    mode: str = "inline",
    body: str = "执行 SOP：{{args}}",
) -> None:
    path = root / ".mewcode" / "skills" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {name} skill\n"
        "allowed_tools: [read_file]\n"
        f"mode: {mode}\n"
        "fork_history: none\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


def app_for_skills(root: Path) -> tuple[MewCodeApp, FakeProvider]:
    registry = new_default_registry()
    runtime = SkillRuntime(
        SkillCatalog.load(
            root,
            root / "user-skills",
            root / "builtin-skills",
        ),
        registry.ordinary_names(),
    )
    app = MewCodeApp(
        [config()],
        registry=registry,
        root=root,
        memory_manager=MemoryManager(root, root / "home"),
        session_repository=SessionRepository(root),
        skill_runtime=runtime,
    )
    app.memory_enabled = False
    app.session_enabled = False
    return app, FakeProvider()


async def submit(app: MewCodeApp, text: str) -> None:
    input_area = app.query_one("#input")
    input_area.text = text
    await app.submit_current_input()


async def wait_until_idle(app: MewCodeApp) -> None:
    for _ in range(200):
        if app.state is SessionState.IDLE and app._stream_task is None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("TUI 回合未在预期时间内结束")


def render(renderable: object) -> str:
    output = StringIO()
    Console(file=output, force_terminal=False).print(renderable)
    return output.getvalue()


def last_command_output(app: MewCodeApp) -> str:
    entries = list(app.query(".command-output-entry"))
    assert entries
    return render(entries[-1].render())


@async_test
async def test_local_commands_do_not_call_provider_or_create_session(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    home = tmp_path / "home"
    project_memory = root / ".mewcode" / "memory"
    user_memory = home / ".mewcode" / "memory"
    project_memory.mkdir(parents=True)
    user_memory.mkdir(parents=True)
    (project_memory / "MEMORY.md").write_text(
        "- api <!-- project_api.md -->\n", encoding="utf-8"
    )
    (user_memory / "MEMORY.md").write_text(
        "- style <!-- user_style.md -->\n", encoding="utf-8"
    )
    app, provider = app_for(root, home=home)

    async with app.run_test():
        app.provider = provider
        for command in ("/help", "/status", "/memory", "/permission", "/session"):
            await submit(app, command)
        assert "当前尚未创建会话" in last_command_output(app)

    assert provider.requests == []
    assert app.runtime is None
    assert app.conv.messages() == []
    sessions_dir = root / ".mewcode" / "sessions"
    assert not sessions_dir.exists() or list(sessions_dir.glob("*.jsonl")) == []


@async_test
async def test_unknown_and_argument_errors_never_reach_agent(tmp_path: Path) -> None:
    app, provider = app_for(tmp_path)

    async with app.run_test():
        app.provider = provider
        await submit(app, "/UNKNOWN")
        assert "/help" in last_command_output(app)
        await submit(app, "/status extra")
        assert "不接受参数" in last_command_output(app)

    assert provider.requests == []
    assert app.runtime is None


@async_test
async def test_plan_do_and_review_share_normal_turn_path(tmp_path: Path) -> None:
    app, provider = app_for(tmp_path)

    async with app.run_test():
        app.provider = provider
        await submit(app, "/plan")
        assert app.mode is Mode.PLAN

        await submit(app, "/do")
        await wait_until_idle(app)
        await submit(app, "/review")
        await wait_until_idle(app)

    assert app.mode is Mode.DEFAULT
    assert len(provider.requests) == 2
    assert provider.requests[0].messages[0].content == EXECUTE_DIRECTIVE
    assert provider.requests[1].messages[-1].content == ""
    assert "审查当前工作区" in provider.requests[1].system.environment
    assert "按严重程度报告可操作的问题" not in provider.requests[1].system.stable
    assert app.session_stats.turns == 2
    assert app.session_stats.input_tokens == 20
    assert app.session_stats.output_tokens == 10
    assert app.runtime is not None
    archive = app.runtime.paths.archive_path.read_text(encoding="utf-8")
    assert '"content":"/do"' not in archive
    assert '"content":"/review"' not in archive
    assert EXECUTE_DIRECTIVE in archive


@async_test
async def test_status_uses_mode_specific_tool_count_and_memory_count(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    memory = root / ".mewcode" / "memory"
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text(
        "- one <!-- one.md -->\n- two <!-- two.md -->\n", encoding="utf-8"
    )
    app, provider = app_for(root, home=tmp_path / "home")

    async with app.run_test():
        app.provider = provider
        await submit(app, "/status")
        default_status = last_command_output(app)
        await submit(app, "/plan")
        await submit(app, "/status")
        plan_status = last_command_output(app)

    assert "可用工具数量: 8" in default_status
    assert "可用工具数量: 4" in plan_status
    assert "已加载记忆条目数: 2" in plan_status
    assert provider.requests == []


@async_test
async def test_inline_skill_is_loaded_on_demand_and_cleared_with_session(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    write_skill(root, "review", body="完整内联 SOP：{{args}}")
    app, provider = app_for_skills(root)

    async with app.run_test():
        app.provider = provider
        await submit(app, "/skill")
        listing = last_command_output(app)
        assert "/review" in listing
        assert "完整内联 SOP" not in listing

        await submit(app, "/review API")
        await wait_until_idle(app)
        request = provider.requests[0]
        assert "完整内联 SOP：API" in request.system.environment
        assert "完整内联 SOP" not in request.system.stable
        assert [tool.name for tool in request.tools] == [
            "read_file",
            "load_skill",
            "install_skill",
        ]
        assert [skill.name for skill in app.skill_runtime.active_skills()] == ["review"]

        await submit(app, "/clear")
        assert app.skill_runtime.active_skills() == ()

    assert provider.requests[0].messages[-1].content == "API"


@async_test
async def test_fork_skill_receives_only_its_argument_and_returns_a_summary(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    write_skill(root, "test", mode="fork", body="隔离 SOP：{{args}}")
    app, provider = app_for_skills(root)

    async with app.run_test():
        app.provider = provider
        await submit(app, "/test unit target")
        await wait_until_idle(app)

    assert len(provider.requests) == 2
    fork_request = provider.requests[0]
    assert [message.content for message in fork_request.messages] == ["unit target"]
    assert "隔离 SOP：unit target" in fork_request.system.environment
    assert [message.role for message in app.conv.messages()] == ["user", "assistant"]
    assert app.conv.messages()[0].content == "执行 Skill test: unit target"
    assert app.conv.messages()[1].content == "回复 2"
    assert "/test" not in app.runtime.paths.archive_path.read_text(encoding="utf-8")


def test_skill_hot_refresh_replaces_dynamic_command_set(tmp_path: Path) -> None:
    root = tmp_path / "project"
    write_skill(root, "review")
    app, _ = app_for_skills(root)

    assert app.command_registry.resolve("review") is not None
    write_skill(root, "custom")
    assert app.refresh_skills() is None
    assert app.command_registry.resolve("custom") is not None


@async_test
async def test_local_command_in_active_session_does_not_append_archive(
    tmp_path: Path,
) -> None:
    app, provider = app_for(tmp_path)

    async with app.run_test():
        app.provider = provider
        await submit(app, "开始会话")
        await wait_until_idle(app)
        assert app.runtime is not None
        path = app.runtime.paths.archive_path
        before = path.read_text(encoding="utf-8")
        await submit(app, "/status")
        after = path.read_text(encoding="utf-8")

    assert before == after


@async_test
async def test_clear_closes_old_session_opens_new_and_resets_ui(
    tmp_path: Path,
) -> None:
    app, provider = app_for(tmp_path)

    async with app.run_test():
        app.provider = provider
        await submit(app, "旧会话消息")
        await wait_until_idle(app)
        assert app.runtime is not None
        old_path = app.runtime.paths.archive_path
        old_id = app.runtime.paths.session_id
        old_content = old_path.read_text(encoding="utf-8")

        await submit(app, "/clear")
        assert app.runtime is not None
        new_path = app.runtime.paths.archive_path
        assert app.runtime.paths.session_id != old_id
        assert new_path != old_path
        assert app.conv.messages() == []
        assert app.session_stats.input_tokens == 0
        assert app.session_stats.output_tokens == 0
        assert app.session_stats.turns == 0
        entries = list(app.query(".timeline-entry"))
        assert len(entries) == 1
        assert "已结束当前会话并开启新会话" in render(entries[0].render())

        await submit(app, "/session")
        assert app.runtime.paths.session_id in last_command_output(app)

    assert old_path.read_text(encoding="utf-8") == old_content
    events = [
        json.loads(line) for line in new_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events == [
        {
            "type": "notice",
            "ts": events[0]["ts"],
            "text": "已结束当前会话并开启新会话",
        }
    ]


@async_test
async def test_clear_alias_executes_without_tab(tmp_path: Path) -> None:
    app, provider = app_for(tmp_path)

    async with app.run_test():
        app.provider = provider
        await submit(app, "/c")

    assert app.runtime is not None
    assert app.conv.messages() == []
    assert provider.requests == []


@async_test
async def test_inline_completion_menu_opens_and_filters_in_place(
    tmp_path: Path,
) -> None:
    app, provider = app_for(tmp_path)

    async with app.run_test() as pilot:
        app.provider = provider
        input_area = app.query_one("#input")
        menu = app.query_one("#command-completion-menu", CommandCompletionMenu)
        main = app.query_one("#main")

        input_area.text = "/"
        await pilot.pause()
        assert menu.display
        assert [command.name for command in menu.commands] == sorted(
            command.name for command in app.command_registry.public_commands()
        )
        assert len(menu.commands) == 15
        assert menu.highlighted == 0
        assert input_area.has_focus
        child_ids = [child.id for child in main.children]
        assert (
            child_ids.index("input")
            < child_ids.index("command-completion-menu")
            < child_ids.index("statusbar")
        )

        input_area.text = "/h"
        await pilot.pause()
        assert [command.name for command in menu.commands] == ["help"]

        input_area.text = "/c"
        await pilot.pause()
        assert [command.name for command in menu.commands] == [
            "clear",
            "commit",
            "compact",
        ]
        assert menu.highlighted == 0

        input_area.text = "/zzz"
        await pilot.pause()
        assert not menu.display
        assert menu.commands == ()
        assert input_area.has_focus
        assert list(app.query(".command-output-entry")) == []

        input_area.text = "/help clear"
        await pilot.pause()
        assert not menu.display

        input_area.text = "普通文本"
        await pilot.pause()
        assert not menu.display

        app.state = SessionState.STREAMING
        input_area.text = "/"
        await pilot.pause()
        assert not menu.display
        app.state = SessionState.IDLE
        app.refresh_command_menu()
        assert menu.display

    assert provider.requests == []
    assert app.runtime is None


@async_test
async def test_completion_keyboard_selection_requires_second_enter(
    tmp_path: Path,
) -> None:
    app, provider = app_for(tmp_path)

    async with app.run_test() as pilot:
        app.provider = provider
        input_area = app.query_one("#input")
        menu = app.query_one("#command-completion-menu", CommandCompletionMenu)
        input_area.text = "/c"
        await pilot.pause()
        timeline_count = len(list(app.query(".timeline-entry")))

        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert input_area.text == "/compact"
        assert not menu.display
        assert len(list(app.query(".timeline-entry"))) == timeline_count
        assert app.runtime is None
        assert input_area.has_focus

        await pilot.press("enter")
        await pilot.pause()
        assert input_area.text == ""
        assert len(list(app.query(".timeline-entry"))) == timeline_count + 1
        assert "当前没有可压缩的会话" in render(
            list(app.query(".timeline-entry"))[-1].render()
        )
        assert input_area.has_focus

    assert provider.requests == []
    assert app.runtime is None


@async_test
async def test_completion_tab_and_mouse_only_fill_canonical_name(
    tmp_path: Path,
) -> None:
    app, provider = app_for(tmp_path)

    async with app.run_test() as pilot:
        app.provider = provider
        input_area = app.query_one("#input")
        menu = app.query_one("#command-completion-menu", CommandCompletionMenu)

        input_area.text = "/h"
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert input_area.text == "/help"
        assert not menu.display
        assert app.runtime is None

        input_area.text = "/c"
        await pilot.pause()
        clicked = await pilot.click(menu, offset=(2, 1))
        await pilot.pause()
        assert clicked
        assert input_area.text == "/clear"
        assert not menu.display
        assert input_area.has_focus

    assert provider.requests == []
    assert app.runtime is None


@async_test
async def test_completion_escape_suppresses_until_edit_and_alias_still_executes(
    tmp_path: Path,
) -> None:
    app, provider = app_for(tmp_path)

    async with app.run_test() as pilot:
        app.provider = provider
        input_area = app.query_one("#input")
        menu = app.query_one("#command-completion-menu", CommandCompletionMenu)

        input_area.text = "/c"
        await pilot.pause()
        assert menu.display
        await pilot.press("escape")
        await pilot.pause()
        assert input_area.text == "/c"
        assert not menu.display
        assert input_area.has_focus

        await pilot.press("tab")
        await pilot.pause()
        assert input_area.text == "/c"
        assert not menu.display

        input_area.text = "/comp"
        await pilot.pause()
        assert [command.name for command in menu.commands] == ["compact"]

        input_area.text = "/c"
        await pilot.pause()
        await pilot.press("escape", "enter")
        await pilot.pause()
        assert app.runtime is not None
        assert input_area.text == ""
        assert input_area.has_focus

    assert provider.requests == []


@async_test
async def test_resume_restores_usage_and_user_turn_count(tmp_path: Path) -> None:
    root = tmp_path / "project"
    session_id = "20260720-120000-abcd"
    path = paths_for(root, session_id).archive_path
    writer = ArchiveWriter(path)
    writer.append_message(Message(role="user", content="第一轮"), model="fake-model")
    writer.append_message(Message(role="assistant", content="完成"))
    writer.append_usage(11, 4)
    writer.append_message(Message(role="user", content="第二轮"))
    writer.append_message(Message(role="assistant", content="完成"))
    writer.append_usage(13, 6)
    writer.close()
    repository = SessionRepository(root)
    summary = repository.list_sessions()[0]
    app, provider = app_for(root)

    async with app.run_test():
        app.provider = provider
        await app._finish_resume(summary)

    assert app.runtime is not None
    assert app.runtime.paths.session_id == session_id
    assert app.session_stats.input_tokens == 24
    assert app.session_stats.output_tokens == 10
    assert app.session_stats.turns == 2
