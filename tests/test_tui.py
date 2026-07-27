from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from functools import wraps
from io import StringIO
from pathlib import Path
from typing import Any, TypeVar

from rich.console import Console
from mewcode.config import ProviderConfig
from mewcode.permission import Mode
from mewcode.hook import Action, Hook, HookCatalog, HookEngine, HookEvent
from mewcode.session.archive import ArchiveWriter
from mewcode.session.paths import paths_for
from mewcode.session.repository import SessionRepository
from mewcode.skill import SkillCatalog, SkillRuntime
from mewcode.llm import Message, Request, StreamEvent, ToolCall, Usage
from mewcode.tool import Registry, Result, new_default_registry
from mewcode.tui.app import MewCodeApp, SessionState
from mewcode.tui.timeline import Timeline
from mewcode.tui.view import (
    approval_block,
    assistant_entry,
    error_entry,
    notice_entry,
    status_bar,
    streaming_block,
    tool_line,
    tool_result_entry,
    tool_result_summary,
    user_entry,
)
from textual.app import App, ComposeResult
from textual.widgets import Collapsible, Static

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
        self.requests = 0

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests += 1
        assert len(req.tools) == 8
        assert req.system.stable
        assert "环境信息" in req.system.environment
        yield StreamEvent(text=f"回复 {self.requests}")
        yield StreamEvent(usage=Usage(10, 5))
        yield StreamEvent(done=True)


class TimelineApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Timeline(id="timeline")


class ToolResultApp(App[None]):
    def compose(self) -> ComposeResult:
        yield tool_result_entry("bash", '{"command":"echo ok"}', "ok", False)


class SuccessfulTool:
    read_only = True

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "测试读取工具"

    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        return Result("第一行\n第二行")


def empty_skill_runtime(tmp_path: Path) -> SkillRuntime:
    return SkillRuntime(
        SkillCatalog.load(
            tmp_path,
            tmp_path / "user-skills",
            tmp_path / "builtin-skills",
        )
    )


async def _wait_until_idle(app: MewCodeApp) -> None:
    for _ in range(200):
        if app.state is SessionState.IDLE and app._stream_task is None:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("TUI 回合未在预期时间内结束")


@async_test
async def test_tui_passes_tools_and_restores_input_for_multiple_turns() -> None:
    config = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="test-key",
        model="fake-model",
    )
    app = MewCodeApp([config], registry=new_default_registry())
    provider = FakeProvider()

    async with app.run_test():
        app.provider = provider
        input_area = app.query_one("#input")

        for question in ("第一问", "第二问"):
            input_area.text = question
            await app.submit_current_input()
            await _wait_until_idle(app)
            assert input_area.read_only is False
            assert input_area.has_focus

    assert provider.requests == 2
    assert app.usage_in == 20
    assert app.usage_out == 10
    assert [message.role for message in app.conv.messages()] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


@async_test
async def test_user_submit_hook_blocks_before_archiving_or_streaming(
    tmp_path: Path,
) -> None:
    config = ProviderConfig(
        name="fake", protocol="openai", api_key="test-key", model="fake-model"
    )
    command = (
        f'"{sys.executable}" -c '
        "\"import sys; print('敏感输入被拒绝', file=sys.stderr); raise SystemExit(2)\""
    )
    hooks = HookEngine(
        HookCatalog(
            (
                Hook(
                    "reject-submit",
                    HookEvent.USER_PROMPT_SUBMIT,
                    None,
                    Action("shell", command=command),
                ),
            )
        )
    )
    app = MewCodeApp(
        [config],
        root=tmp_path,
        registry=Registry(),
        skill_runtime=empty_skill_runtime(tmp_path),
        hook_engine=hooks,
    )
    provider = FakeProvider()

    async with app.run_test():
        app.provider = provider
        input_area = app.query_one("#input")
        input_area.text = "请删除文件"
        await app.submit_current_input()

        assert input_area.text == "请删除文件"
        assert app.conv.messages() == []
        assert app.session_stats.turns == 0
        assert provider.requests == 0
        assert app.state is SessionState.IDLE


@async_test
async def test_session_start_prompt_is_hidden_and_consumed_once(tmp_path: Path) -> None:
    class ReminderProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.reminders: list[str] = []

        async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
            self.requests += 1
            self.reminders.append(req.reminder)
            yield StreamEvent(text="完成")
            yield StreamEvent(done=True)

    config = ProviderConfig(
        name="fake", protocol="openai", api_key="test-key", model="fake-model"
    )
    hooks = HookEngine(
        HookCatalog(
            (
                Hook(
                    "session-hint",
                    HookEvent.SESSION_START,
                    None,
                    Action("prompt", text="仅首轮提醒"),
                ),
            )
        )
    )
    app = MewCodeApp(
        [config],
        root=tmp_path,
        registry=Registry(),
        skill_runtime=empty_skill_runtime(tmp_path),
        hook_engine=hooks,
    )
    provider = ReminderProvider()

    async with app.run_test():
        app.provider = provider
        input_area = app.query_one("#input")
        input_area.text = "第一轮"
        await app.submit_current_input()
        await _wait_until_idle(app)
        input_area.text = "第二轮"
        await app.submit_current_input()
        await _wait_until_idle(app)

    assert provider.reminders == ["仅首轮提醒", ""]
    assert all("仅首轮提醒" not in message.content for message in app.conv.messages())


@async_test
async def test_clear_and_resume_dispatch_session_lifecycle_hooks(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    session_id = "20260723-120000-abcd"
    writer = ArchiveWriter(paths_for(root, session_id).archive_path)
    writer.append_message(Message(role="user", content="历史消息"), model="fake-model")
    writer.close()
    repository = SessionRepository(root)
    summary = repository.list_sessions()[0]
    config = ProviderConfig(
        name="fake", protocol="openai", api_key="test-key", model="fake-model"
    )
    hooks = HookEngine(
        HookCatalog(
            (
                Hook(
                    "session-end",
                    HookEvent.SESSION_END,
                    None,
                    Action("prompt", text="结束"),
                    only_once=True,
                ),
                Hook(
                    "session-resume",
                    HookEvent.SESSION_RESUME,
                    None,
                    Action("prompt", text="恢复"),
                    only_once=True,
                ),
            )
        )
    )
    app = MewCodeApp(
        [config],
        root=root,
        registry=Registry(),
        skill_runtime=empty_skill_runtime(root),
        session_repository=repository,
        hook_engine=hooks,
    )
    provider = FakeProvider()

    async with app.run_test():
        app.provider = provider
        app._ensure_runtime()
        ending_state = app.runtime.hook_state
        await app.command_control.clear_session()
        assert ending_state.executed == {"session-end"}
        await app._finish_resume(summary)
        assert app.runtime is not None
        assert app.runtime.hook_state.executed == {"session-resume"}


@async_test
async def test_timeline_highlights_each_user_turn_and_keeps_input_bottom() -> None:
    config = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="test-key",
        model="fake-model",
    )
    app = MewCodeApp([config], registry=new_default_registry())
    provider = FakeProvider()

    async with app.run_test(size=(48, 14)):
        app.provider = provider
        input_area = app.query_one("#input")
        for question in ("第一问", "第二问", "第三问"):
            input_area.text = question
            await app.submit_current_input()
            await _wait_until_idle(app)

        users = list(app.query(".user-entry"))
        timeline = app.query_one("#timeline", Timeline)
        assert len(users) == 3
        assert all(entry.has_class("timeline-entry") for entry in users)
        assert timeline.region.bottom <= input_area.region.y
        assert app.query_one("#statusbar", Static).region.y > input_area.region.y


@async_test
async def test_timeline_only_follows_when_view_is_at_bottom() -> None:
    app = TimelineApp()

    async with app.run_test(size=(40, 8)) as pilot:
        timeline = app.query_one("#timeline", Timeline)
        for index in range(12):
            await timeline.append(Static(f"条目 {index}\n第二行"))
        await pilot.pause()
        assert timeline.scroll_y == timeline.max_scroll_y

        timeline.scroll_to(y=0, animate=False, immediate=True)
        await pilot.pause()
        before = timeline.scroll_y
        await timeline.append(Static("历史阅读期间的新增条目\n第二行"))
        await pilot.pause()
        assert timeline.scroll_y == before

        timeline.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        await timeline.append(Static("恢复跟随后的新增条目\n第二行"))
        await pilot.pause()
        assert timeline.scroll_y == timeline.max_scroll_y


@async_test
async def test_tool_result_expands_and_collapses_when_title_is_clicked() -> None:
    app = ToolResultApp()

    async with app.run_test() as pilot:
        tool = app.query_one(Collapsible)
        title = tool.query_one("CollapsibleTitle")
        assert tool.collapsed is True
        assert await pilot.click(title, offset=(0, 0))
        await pilot.pause()
        assert tool.collapsed is False
        assert await pilot.click(title, offset=(0, 0))
        await pilot.pause()
        assert tool.collapsed is True


def test_semantic_entries_and_collapsed_tool_result_are_safe() -> None:
    user = user_entry("完整用户问题")
    assistant = assistant_entry("助手回复", 2)
    error = error_entry(RuntimeError("network"))
    notice = notice_entry("已取消")
    tool = tool_result_entry(
        "write_file",
        '{"path":"a.py","content":"secret file content"}',
        "\n".join(f"line {index}" for index in range(20)),
        False,
    )

    assert user.has_class("user-entry")
    assert assistant.has_class("assistant-entry")
    assert error.has_class("error-entry")
    assert notice.has_class("notice-entry")
    assert tool.has_class("tool-result-entry")
    assert tool.collapsed is True
    assert "write_file" in tool.title and "a.py" in tool.title
    assert "secret file content" not in tool.title
    rendered = _render(
        tool_result_summary("\n".join(f"line {index}" for index in range(20)), False)
    )
    assert "line 7" in rendered
    assert "line 8" not in rendered
    assert "[truncated]" in rendered


@async_test
async def test_tool_events_create_collapsed_timeline_result_and_clear_activity(
    tmp_path: Path,
) -> None:
    class ToolProvider(FakeProvider):
        async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
            self.requests += 1
            if self.requests == 1:
                yield StreamEvent(text="先读取")
                yield StreamEvent(
                    tool_calls=[ToolCall("call-1", "read_file", '{"path":"a.txt"}')]
                )
                yield StreamEvent(done=True)
                return
            yield StreamEvent(text="读取完成")
            yield StreamEvent(done=True)

    config = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="test-key",
        model="fake-model",
    )
    registry = Registry()
    registry.register(SuccessfulTool())
    app = MewCodeApp(
        [config], registry=registry, skill_runtime=empty_skill_runtime(tmp_path)
    )
    provider = ToolProvider()

    async with app.run_test() as pilot:
        app.provider = provider
        input_area = app.query_one("#input")
        input_area.text = "读取测试文件"
        await app.submit_current_input()
        await _wait_until_idle(app)

        tool = app.query_one(Collapsible)
        assert tool.collapsed is True
        assert "工具 read_file · 完成" in tool.title
        tool.collapsed = False
        await pilot.pause()
        assert tool.collapsed is False
        assert "第一行" in _render(
            tool.query_one(".tool-result-detail", Static).render()
        )
        assert _render(app.query_one("#streaming", Static).render()).strip() == ""
        assert input_area.read_only is False and input_area.has_focus


def _render(renderable: object) -> str:
    output = StringIO()
    Console(file=output, force_terminal=False).print(renderable)
    return output.getvalue()


@async_test
async def test_tui_plan_and_do_switch_mode_and_use_directive() -> None:
    config = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="test-key",
        model="fake-model",
    )
    app = MewCodeApp([config], registry=new_default_registry())
    provider = FakeProvider()

    async with app.run_test():
        app.provider = provider
        input_area = app.query_one("#input")
        input_area.text = "/plan"
        await app.submit_current_input()
        assert app.mode is Mode.PLAN
        assert app.state is SessionState.IDLE

        input_area.text = "/do"
        await app.submit_current_input()
        await _wait_until_idle(app)

    assert app.mode is Mode.NORMAL
    assert provider.requests == 1
    assert app.conv.messages()[0].content == "请按上面的计划开始执行。"


@async_test
async def test_tui_escape_cancels_streaming_turn_without_exiting() -> None:
    class BlockingProvider(FakeProvider):
        async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
            self.requests += 1
            await asyncio.sleep(5)
            yield StreamEvent(text="不应出现")
            yield StreamEvent(done=True)

    config = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="test-key",
        model="fake-model",
    )
    app = MewCodeApp([config], registry=new_default_registry())
    provider = BlockingProvider()

    async with app.run_test() as pilot:
        app.provider = provider
        input_area = app.query_one("#input")
        input_area.text = "开始"
        await app.submit_current_input()
        await asyncio.sleep(0)
        await pilot.press("escape")
        await _wait_until_idle(app)

        assert input_area.read_only is False
        assert input_area.has_focus
        assert app.conv.last_role() == "assistant"


@async_test
async def test_tui_provider_error_keeps_conversation_valid_and_recovers() -> None:
    class ErrorProvider(FakeProvider):
        async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
            self.requests += 1
            yield StreamEvent(err=RuntimeError("network"))

    config = ProviderConfig(
        name="fake",
        protocol="openai",
        api_key="test-key",
        model="fake-model",
    )
    app = MewCodeApp([config], registry=new_default_registry())
    provider = ErrorProvider()

    async with app.run_test():
        app.provider = provider
        input_area = app.query_one("#input")
        input_area.text = "触发错误"
        await app.submit_current_input()
        await _wait_until_idle(app)

        assert input_area.read_only is False
        assert input_area.has_focus
        assert app.conv.last_role() == "assistant"
        assert "请求出错" in app.conv.messages()[-1].content


@async_test
async def test_tui_approval_menu_allows_once_and_mode_cycles(tmp_path: Path) -> None:
    class ApprovalProvider(FakeProvider):
        async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
            self.requests += 1
            if self.requests == 1:
                yield StreamEvent(
                    tool_calls=[
                        ToolCall(
                            "write-1",
                            "write_file",
                            '{"path":"a.txt","content":"x"}',
                        )
                    ]
                )
                yield StreamEvent(done=True)
                return
            yield StreamEvent(text="写入完成")
            yield StreamEvent(done=True)

    config = ProviderConfig(
        name="fake", protocol="openai", api_key="test-key", model="fake-model"
    )
    registry = Registry()
    log: list[str] = []
    registry.register(RecordingWriteTool(log))
    app = MewCodeApp(
        [config], registry=registry, skill_runtime=empty_skill_runtime(tmp_path)
    )
    provider = ApprovalProvider()

    async with app.run_test() as pilot:
        app.provider = provider
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.mode is Mode.ACCEPT_EDITS
        for expected in (Mode.PLAN, Mode.BYPASS, Mode.DEFAULT):
            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.mode is expected
        assert app.mode is Mode.DEFAULT

        input_area = app.query_one("#input")
        input_area.text = "写入文件"
        await app.submit_current_input()
        for _ in range(100):
            if app.state is SessionState.APPROVING:
                break
            await asyncio.sleep(0.01)
        assert app.state is SessionState.APPROVING
        assert app.pending is not None
        assert "允许本会话" in _render(
            approval_block(
                app.pending.name,
                app.pending.args,
                app.pending.reason,
                app.approve_cursor,
            )
        )
        await pilot.press("1")
        await _wait_until_idle(app)

    assert log == ["write"]
    assert app.conv.messages()[-1].content == "写入完成"


@async_test
async def test_tui_escape_cancels_approval_and_allows_followup(
    tmp_path: Path,
) -> None:
    class ApprovalThenReplyProvider(FakeProvider):
        async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
            self.requests += 1
            if self.requests == 1:
                yield StreamEvent(
                    tool_calls=[
                        ToolCall(
                            "write-1",
                            "write_file",
                            '{"path":"a.txt","content":"x"}',
                        )
                    ]
                )
                yield StreamEvent(done=True)
                return
            yield StreamEvent(text="后续正常")
            yield StreamEvent(done=True)

    config = ProviderConfig(
        name="fake", protocol="openai", api_key="test-key", model="fake-model"
    )
    registry = Registry()
    registry.register(RecordingWriteTool([]))
    app = MewCodeApp(
        [config], registry=registry, skill_runtime=empty_skill_runtime(tmp_path)
    )
    provider = ApprovalThenReplyProvider()

    async with app.run_test() as pilot:
        app.provider = provider
        input_area = app.query_one("#input")
        input_area.text = "需要批准"
        await app.submit_current_input()
        for _ in range(100):
            if app.state is SessionState.APPROVING:
                break
            await asyncio.sleep(0.01)
        assert app.state is SessionState.APPROVING
        await pilot.press("escape")
        await _wait_until_idle(app)
        assert input_area.read_only is False and input_area.has_focus

        input_area.text = "继续"
        await app.submit_current_input()
        await _wait_until_idle(app)

    assert app.conv.messages()[-1].content == "后续正常"


class RecordingWriteTool:
    read_only = False

    def __init__(self, log: list[str]) -> None:
        self.log = log

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "写入测试文件"

    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        self.log.append("write")
        return Result("done")


def test_tool_line_only_previews_safe_key_argument() -> None:
    rendered = tool_line(
        "write_file",
        '{"path":"a.py","content":"secret file content"}',
    )

    assert rendered.plain == "● write_file(a.py)"
    assert "secret file content" not in rendered.plain


def test_tool_result_summary_limits_visible_lines() -> None:
    rendered = tool_result_summary("\n".join(f"line {i}" for i in range(20)), False)

    assert "line 7" in rendered.plain
    assert "line 8" not in rendered.plain
    assert "[truncated]" in rendered.plain


def test_approval_block_shows_all_four_options() -> None:
    rendered = _render(approval_block("write_file", '{"path":"a.py"}', "需要确认", 1))

    assert "允许本次" in rendered
    assert "允许本会话" in rendered
    assert "永久允许" in rendered
    assert "拒绝本次" in rendered
    assert "> 2." in rendered


def test_status_bar_shows_plan_mode_and_compact_usage() -> None:
    rendered = status_bar("model", Mode.PLAN, 1200, 9)
    output = StringIO()
    Console(file=output, force_terminal=False).print(rendered)

    text = output.getvalue()
    assert "权限: [PLAN]" in text
    assert "1.2k" in text
    assert "↑" in text and "↓" in text


def test_streaming_block_uses_chinese_activity_text() -> None:
    rendered = _render(streaming_block("正在回复", 3, 2))

    assert "生成中" in rendered
    assert "第 2 轮" in rendered
