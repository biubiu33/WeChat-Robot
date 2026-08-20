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


class FailingObserverDriver(FakeDriver):
    def wait_for_events(self, stop) -> list[WechatDesktopEvent]:
        stop.set()
        raise WechatUiaError("未找到微信好友 'A' 的搜索结果")


class FakeRuntime:
    def __init__(self, replies: dict[str, WechatReply] | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[tuple[str, str]] = []
        self.deliveries: list[tuple[str, tuple[str, ...]]] = []

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
        "safe",
        2,
        max_chars,
        "INFO",
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
