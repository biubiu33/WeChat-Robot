from __future__ import annotations

import asyncio
import logging
from functools import wraps
from pathlib import Path

from mewcode.wechat.bot import WechatBot
from mewcode.wechat.config import WechatConfig
from mewcode.wechat.models import WechatDesktopEvent, WechatReply
from mewcode.wechat.runtime import WechatTurnCancelled
from mewcode.wechat.store import WechatStateStore
from mewcode.wechat.uia_client import WechatUiaError


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


class FakeDriver:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail_on = ""
        self.group_mentions: list[tuple[str, str, str]] = []

    def establish_baseline(self) -> None:
        pass

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def wait_for_events(self, stop) -> list[WechatDesktopEvent]:
        stop.wait(0.01)
        return []

    def send_text(self, event: WechatDesktopEvent, text: str) -> None:
        if text == self.fail_on:
            raise RuntimeError("send-secret")
        self.sent.append((event.conversation_name, text))

    def send_group_first(
        self, event: WechatDesktopEvent, sender_name: str, text: str
    ) -> tuple[bool, str]:
        self.group_mentions.append((event.conversation_name, sender_name, text))
        self.sent.append((event.conversation_name, f"@{sender_name}\n{text}"))
        return False, "test fallback"


class FailingObserverDriver(FakeDriver):
    def wait_for_events(self, stop) -> list[WechatDesktopEvent]:
        stop.set()
        raise WechatUiaError("未找到微信好友 'A' 的搜索结果")


class FakeRuntime:
    def __init__(self, replies: dict[str, WechatReply] | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[tuple[str, str]] = []
        self.deliveries: list[tuple[str, tuple[str, ...]]] = []
        self.group_calls: list[tuple[str, str, str, tuple]] = []

    async def reply(
        self,
        name: str,
        text: str,
        cancel: asyncio.Event,
        on_tool_stage=None,
    ) -> WechatReply:
        self.calls.append((name, text))
        await asyncio.sleep(0)
        return self.replies.get(text, WechatReply((f"reply:{text}",), False))

    def record_delivery(self, name: str, messages: list[str]) -> None:
        self.deliveries.append((name, tuple(messages)))

    async def reply_group(
        self,
        name: str,
        sender: str,
        text: str,
        history: tuple,
        cancel: asyncio.Event,
        on_tool_stage=None,
    ) -> WechatReply:
        del cancel, on_tool_stage
        self.group_calls.append((name, sender, text, history))
        return self.replies.get(text, WechatReply((f"reply:{text}",), False))

    async def close(self) -> None:
        pass


class BlockingRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def reply(
        self,
        name: str,
        text: str,
        cancel: asyncio.Event,
        on_tool_stage=None,
    ) -> WechatReply:
        self.calls.append((name, text))
        if text == "slow":
            self.started.set()
            await cancel.wait()
            raise WechatTurnCancelled
        return WechatReply((f"reply:{text}",), False)


class BlockingGroupRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def reply_group(
        self,
        name: str,
        sender: str,
        text: str,
        history: tuple,
        cancel: asyncio.Event,
        on_tool_stage=None,
    ) -> WechatReply:
        del history, on_tool_stage
        self.group_calls.append((name, sender, text, ()))
        if text == "慢问题":
            self.started.set()
            await self.release.wait()
            assert not cancel.is_set()
        return WechatReply((f"reply:{text}",), False)


class ToolRuntime(FakeRuntime):
    async def reply(
        self,
        name: str,
        text: str,
        cancel: asyncio.Event,
        on_tool_stage=None,
    ) -> WechatReply:
        self.calls.append((name, text))
        assert on_tool_stage is not None
        await on_tool_stage("我查一下相关资料。")
        return WechatReply(
            ("专业正文",), False, "来源：\n1. 示例 — https://example.com"
        )


class BlockingToolRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.status_sent = asyncio.Event()

    async def reply(
        self,
        name: str,
        text: str,
        cancel: asyncio.Event,
        on_tool_stage=None,
    ) -> WechatReply:
        self.calls.append((name, text))
        if text != "search":
            return WechatReply((f"reply:{text}",), False)
        assert on_tool_stage is not None
        await on_tool_stage("我查一下相关资料。")
        self.status_sent.set()
        await cancel.wait()
        raise WechatTurnCancelled


class FailingRuntime(FakeRuntime):
    async def reply(
        self,
        name: str,
        text: str,
        cancel: asyncio.Event,
        on_tool_stage=None,
    ) -> WechatReply:
        del cancel, on_tool_stage
        self.calls.append((name, text))
        raise RuntimeError(r"secret-key C:\private\trace.py")


def config(max_chars: int = 20) -> WechatConfig:
    return WechatConfig(
        True,
        "fake",
        ("A", "B"),
        2,
        max_chars,
        "INFO",
    )


def group_config(max_chars: int = 20) -> WechatConfig:
    return WechatConfig(
        True,
        "fake",
        (),
        2,
        max_chars,
        "INFO",
        allowed_groups=("测试群聊",),
        self_names=("biubiubiu仿生人",),
    )


def event(
    event_id: str,
    name: str,
    text: str,
    *,
    fingerprint: str | None = None,
) -> WechatDesktopEvent:
    return WechatDesktopEvent(
        event_id,
        fingerprint or event_id,
        f"row-{name}",
        name,
        name,
        text,
        1.0,
        True,
        True,
    )


def group_event(
    event_id: str,
    sender: str,
    text: str,
    *,
    is_at: bool,
) -> WechatDesktopEvent:
    return WechatDesktopEvent(
        event_id,
        event_id,
        "row-测试群聊",
        "测试群聊",
        sender,
        text,
        1.0,
        True,
        False,
        is_at=is_at,
        raw_text=(f"@biubiubiu仿生人 {text}" if is_at else text),
    )


async def start_consumer(bot: WechatBot) -> None:
    bot._consumer = asyncio.create_task(bot._consume())


async def wait_idle(bot: WechatBot, settle: float = 0.03) -> None:
    await asyncio.sleep(settle)
    await asyncio.wait_for(bot._queue.join(), 1)
    await asyncio.sleep(0)


@async_test
async def test_allowlist_dedup_aggregation_and_fifo(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = FakeRuntime()
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)

    assert bot.submit_event(event("x", "陌生人", "ignored")) is False
    assert bot.submit_event(event("1", "A", "first")) is True
    assert bot.submit_event(event("2", "A", "supplement")) is True
    assert bot.submit_event(event("3", "B", "second")) is True
    assert bot.submit_event(event("4", "A", "duplicate", fingerprint="1")) is False
    await wait_idle(bot)

    assert runtime.calls == [
        ("A", "first\nsupplement"),
        ("B", "second"),
    ]
    assert driver.sent == [
        ("A", "reply:first\nsupplement"),
        ("B", "reply:second"),
    ]
    assert store.is_processed("1")
    assert store.is_processed("2")
    assert store.is_processed("3")
    await bot.stop()


@async_test
async def test_queued_batch_becomes_stale_when_friend_supplements(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    runtime = FakeRuntime()
    bot = WechatBot(config(), FakeDriver(), runtime, store, quiet_seconds=0.01)

    bot.submit_event(event("1", "A", "old"))
    await asyncio.sleep(0.02)
    bot.submit_event(event("2", "A", "new"))
    await start_consumer(bot)
    await wait_idle(bot, 0.04)

    assert runtime.calls == [("A", "old\nnew")]
    assert store.is_processed("1")
    assert store.is_processed("2")
    await bot.stop()


@async_test
async def test_quiet_window_waits_and_resets_after_supplement(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    runtime = FakeRuntime()
    bot = WechatBot(config(), FakeDriver(), runtime, store, quiet_seconds=0.05)
    await start_consumer(bot)

    bot.submit_event(event("1", "A", "first"))
    await asyncio.sleep(0.03)
    assert runtime.calls == []
    bot.submit_event(event("2", "A", "supplement"))
    await asyncio.sleep(0.03)
    assert runtime.calls == []
    await wait_idle(bot, 0.04)

    assert runtime.calls == [("A", "first\nsupplement")]
    await bot.stop()


@async_test
async def test_same_friend_interrupts_active_turn_but_other_friend_does_not(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    runtime = BlockingRuntime()
    bot = WechatBot(config(), FakeDriver(), runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    bot.submit_event(event("1", "A", "slow"))
    await runtime.started.wait()

    bot.submit_event(event("2", "B", "other"))
    await asyncio.sleep(0)
    assert bot._active is not None and not bot._active.cancel.is_set()
    bot.submit_event(event("3", "A", "changed"))
    await wait_idle(bot)

    assert runtime.calls == [
        ("A", "slow"),
        ("B", "other"),
        ("A", "changed"),
    ]
    assert all("已取消" not in text for _, text in bot._driver.sent)
    await bot.stop()


@async_test
async def test_tool_status_body_and_source_are_atomic_and_recorded(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = ToolRuntime()
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    bot.submit_event(event("1", "A", "search"))
    await wait_idle(bot)

    assert driver.sent == [
        ("A", "我查一下相关资料。"),
        ("A", "专业正文"),
        ("A", "来源：\n1. 示例 — https://example.com"),
    ]
    assert runtime.deliveries == [
        (
            "A",
            (
                "我查一下相关资料。",
                "专业正文",
                "来源：\n1. 示例 — https://example.com",
            ),
        )
    ]
    await bot.stop()


@async_test
async def test_new_message_during_tool_cancels_old_result_without_notice(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = BlockingToolRuntime()
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    bot.submit_event(event("1", "A", "search"))
    await runtime.status_sent.wait()

    bot.submit_event(event("2", "A", "changed"))
    await wait_idle(bot)

    assert driver.sent == [
        ("A", "我查一下相关资料。"),
        ("A", "reply:changed"),
    ]
    assert all("取消" not in text for _, text in driver.sent)
    assert runtime.deliveries[0] == ("A", ("我查一下相关资料。",))
    await bot.stop()


@async_test
async def test_new_message_during_chat_delay_stops_remaining_bubbles(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = FakeRuntime({"chat": WechatReply(("one", "two", "three"), True)})
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)

    async def interrupt(cancel: asyncio.Event, delay: float) -> bool:
        del delay
        bot.submit_event(event("2", "A", "changed"))
        await asyncio.sleep(0)
        return not cancel.is_set()

    bot._wait_or_cancel = interrupt
    await start_consumer(bot)
    bot.submit_event(event("1", "A", "chat"))
    await wait_idle(bot)

    assert driver.sent[0] == ("A", "one")
    assert ("A", "two") not in driver.sent
    assert ("A", "three") not in driver.sent
    assert runtime.deliveries[0] == ("A", ("one",))
    await bot.stop()


@async_test
async def test_send_failure_stops_batch_and_records_only_success(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    driver.fail_on = "two"
    runtime = FakeRuntime({"chat": WechatReply(("one", "two", "three"), False)})
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    bot.submit_event(event("1", "A", "chat"))
    await wait_idle(bot)

    assert driver.sent == [("A", "one")]
    assert runtime.deliveries == [("A", ("one",))]
    await bot.stop()


@async_test
async def test_first_send_failure_records_no_visible_history(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    driver.fail_on = "one"
    runtime = FakeRuntime({"chat": WechatReply(("one", "two"), False)})
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    bot.submit_event(event("1", "A", "chat"))
    await wait_idle(bot)

    assert driver.sent == []
    assert runtime.deliveries == [("A", ())]
    await bot.stop()


@async_test
async def test_runtime_failure_sends_only_controlled_plain_text(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = FailingRuntime()
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    bot.submit_event(event("1", "A", "fail"))
    await wait_idle(bot)

    assert driver.sent == [("A", "处理失败，请稍后再试。")]
    assert "secret" not in driver.sent[0][1]
    assert runtime.deliveries == [("A", ("处理失败，请稍后再试。",))]
    await bot.stop()


@async_test
async def test_stop_cancels_pending_timer_and_active_turn(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    runtime = BlockingRuntime()
    bot = WechatBot(config(), FakeDriver(), runtime, store, quiet_seconds=0)
    await start_consumer(bot)

    bot.submit_event(event("1", "A", "slow"))
    await runtime.started.wait()
    bot._quiet_seconds = 1
    bot.submit_event(event("2", "B", "pending"))
    timer = bot._pending["B"].timer
    assert timer is not None

    await asyncio.wait_for(bot.stop(), 1)

    assert timer.done()
    assert bot._consumer is not None and bot._consumer.done()


@async_test
async def test_cancel_text_is_an_ordinary_message(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    runtime = FakeRuntime()
    bot = WechatBot(config(), FakeDriver(), runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    bot.submit_event(event("1", "A", "/cancel"))
    await wait_idle(bot)

    assert runtime.calls == [("A", "/cancel")]
    assert runtime.deliveries == [("A", ("reply:/cancel",))]
    await bot.stop()


@async_test
async def test_observer_log_includes_controlled_uia_error_reason(
    tmp_path: Path,
    caplog,
) -> None:
    store = WechatStateStore(tmp_path)
    bot = WechatBot(config(), FailingObserverDriver(), FakeRuntime(), store)
    bot._loop = asyncio.get_running_loop()
    caplog.set_level(logging.ERROR, logger="mewcode.wechat")

    bot._observe()

    assert "WechatUiaError" in caplog.text
    assert "未找到微信好友 'A' 的搜索结果" in caplog.text
    store.close()


@async_test
async def test_group_members_have_independent_windows_and_only_at_enters_batch(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = FakeRuntime()
    bot = WechatBot(group_config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)

    assert bot.submit_event(group_event("1", "张三", "普通消息", is_at=False))
    assert bot.submit_event(group_event("2", "张三", "问题A", is_at=True))
    assert bot.submit_event(group_event("3", "李四", "问题B", is_at=True))
    assert bot.submit_event(group_event("4", "张三", "未@补充", is_at=False))
    await wait_idle(bot)

    assert [(name, sender, text) for name, sender, text, _ in runtime.group_calls] == [
        ("测试群聊", "张三", "问题A"),
        ("测试群聊", "李四", "问题B"),
    ]
    assert driver.group_mentions == [
        ("测试群聊", "张三", "reply:问题A"),
        ("测试群聊", "李四", "reply:问题B"),
    ]
    assert runtime.deliveries == []
    await bot.stop()


@async_test
async def test_group_context_rolls_at_twenty_and_freezes_on_enqueue(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    runtime = FakeRuntime()
    bot = WechatBot(group_config(), FakeDriver(), runtime, store, quiet_seconds=0.01)
    for index in range(21):
        bot.submit_event(
            group_event(str(index), f"成员{index % 2}", f"消息{index}", is_at=False)
        )
    bot.submit_event(group_event("question", "张三", "问题", is_at=True))
    await asyncio.sleep(0.02)
    bot.submit_event(group_event("later", "王五", "后来消息", is_at=False))
    await start_consumer(bot)
    await wait_idle(bot)

    [(_, _, _, history)] = runtime.group_calls
    assert len(history) == 20
    assert history[0].text == "消息2"
    assert history[-1].text.startswith("@biubiubiu仿生人 问题")
    assert all(item.text != "后来消息" for item in history)
    await bot.stop()


@async_test
async def test_group_reply_mentions_only_first_bubble(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = FakeRuntime({"聊天": WechatReply(("一", "二", "三"), False)})
    bot = WechatBot(group_config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    bot.submit_event(group_event("1", "张三", "聊天", is_at=True))
    await wait_idle(bot)

    assert driver.group_mentions == [("测试群聊", "张三", "一")]
    assert driver.sent == [
        ("测试群聊", "@张三\n一"),
        ("测试群聊", "二"),
        ("测试群聊", "三"),
    ]
    await bot.stop()


@async_test
async def test_new_group_at_never_cancels_active_group_reply(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    runtime = BlockingGroupRuntime()
    bot = WechatBot(group_config(), FakeDriver(), runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    bot.submit_event(group_event("1", "张三", "慢问题", is_at=True))
    await runtime.started.wait()

    bot.submit_event(group_event("2", "李四", "后续问题", is_at=True))
    await asyncio.sleep(0)
    assert bot._active is not None
    assert not bot._active.cancel.is_set()
    runtime.release.set()
    await wait_idle(bot)

    assert [(sender, text) for _, sender, text, _ in runtime.group_calls] == [
        ("张三", "慢问题"),
        ("李四", "后续问题"),
    ]
    await bot.stop()


@async_test
async def test_same_group_member_opens_new_window_after_first_batch_is_queued(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    runtime = BlockingGroupRuntime()
    bot = WechatBot(group_config(), FakeDriver(), runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    bot.submit_event(group_event("1", "张三", "慢问题", is_at=True))
    await runtime.started.wait()

    bot.submit_event(group_event("2", "张三", "第二批", is_at=True))
    await asyncio.sleep(0)
    assert bot._active is not None
    assert not bot._active.cancel.is_set()
    runtime.release.set()
    await wait_idle(bot)

    assert [(sender, text) for _, sender, text, _ in runtime.group_calls] == [
        ("张三", "慢问题"),
        ("张三", "第二批"),
    ]
    await bot.stop()


@async_test
async def test_same_group_member_merges_mentions_inside_one_quiet_window(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    runtime = FakeRuntime()
    bot = WechatBot(group_config(), FakeDriver(), runtime, store, quiet_seconds=0.01)
    bot.submit_event(group_event("1", "张三", "问题一", is_at=True))
    bot.submit_event(group_event("2", "张三", "问题二", is_at=True))
    await start_consumer(bot)
    await wait_idle(bot)

    assert [(sender, text) for _, sender, text, _ in runtime.group_calls] == [
        ("张三", "问题一\n问题二")
    ]
    await bot.stop()
