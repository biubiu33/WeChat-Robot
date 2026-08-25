from __future__ import annotations

import asyncio
import logging
from functools import wraps
from pathlib import Path

import pytest
from PIL import Image

from mewcode.wechat.bot import WechatBot
from mewcode.wechat.config import WechatConfig
from mewcode.wechat.models import (
    ImageCapture,
    MessageReference,
    ResolvedReference,
    WechatDesktopEvent,
    WechatReply,
)
from mewcode.wechat.runtime import WechatTurnCancelled
from mewcode.wechat.store import WechatStateStore
from mewcode.wechat.uia_client import WechatReferenceTargetError, WechatUiaError


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
        self.materialized: list[Path] = []
        self.capture_failure = False
        self.reference_result: ResolvedReference | Exception | None = None

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

    def materialize_private_image(
        self, event: WechatDesktopEvent, target_dir: Path
    ) -> ImageCapture | None:
        if self.capture_failure:
            return None
        path = target_dir / f"{event.event_id}.png"
        Image.new("RGB", (4, 4), "red").save(path, format="PNG")
        self.materialized.append(path)
        return ImageCapture(path, degraded=event.event_id.startswith("degraded"))

    def materialize_reference(
        self, event: WechatDesktopEvent, target_dir: Path
    ) -> ResolvedReference:
        result = self.reference_result
        if isinstance(result, Exception):
            raise result
        if result is not None:
            capture = result.capture
            if capture is not None:
                path = target_dir / f"reference-{event.event_id}.png"
                Image.new("RGB", (4, 4), "blue").save(path, format="PNG")
                self.materialized.append(path)
                return ResolvedReference(
                    result.source,
                    result.content,
                    ImageCapture(path, result.degraded),
                    result.degraded,
                    result.strategy,
                )
            return result
        assert event.reference is not None
        return ResolvedReference(
            event.reference,
            event.reference.preview,
            degraded=True,
            strategy="preview",
        )


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
        self.image_calls: list[tuple[str, str, tuple]] = []
        self.reference_calls: list[tuple[str, bool]] = []

    async def reply(
        self,
        name: str,
        text: str,
        cancel: asyncio.Event,
        on_tool_stage=None,
        *,
        images=(),
        reference_turn=False,
    ) -> WechatReply:
        self.calls.append((name, text))
        self.reference_calls.append((name, reference_turn))
        if images:
            self.image_calls.append((name, text, tuple(images)))
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
        *,
        images=(),
        reference_turn=False,
    ) -> WechatReply:
        del cancel, on_tool_stage
        if images:
            self.image_calls.append((name, text, tuple(images)))
        self.reference_calls.append((name, reference_turn))
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


def combined_config(max_chars: int = 20) -> WechatConfig:
    return WechatConfig(
        True,
        "fake",
        ("A",),
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


def image_event(event_id: str, name: str = "A") -> WechatDesktopEvent:
    return WechatDesktopEvent(
        event_id,
        event_id,
        f"row-{name}",
        name,
        name,
        "[图片]",
        1.0,
        True,
        True,
        message_key=event_id,
        message_kind="image",
        bounds=(1, 2, 20, 30),
    )


def reference_event(
    event_id: str,
    name: str,
    question: str,
    *,
    kind: str = "text",
    preview: str = "被引用内容",
    sender: str = "原发送者",
) -> WechatDesktopEvent:
    base = event(event_id, name, question)
    return WechatDesktopEvent(
        **{
            **base.__dict__,
            "reference": MessageReference(sender, preview, kind),
        }
    )


def group_reference_event(
    event_id: str,
    sender: str,
    question: str,
    *,
    kind: str = "text",
    preview: str = "被引用内容",
    is_at: bool = True,
) -> WechatDesktopEvent:
    base = group_event(event_id, sender, question, is_at=is_at)
    return WechatDesktopEvent(
        **{
            **base.__dict__,
            "reference": MessageReference("群成员甲", preview, kind),
        }
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
async def test_private_image_only_triggers_one_multimodal_reply_and_cleans_tmp(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = FakeRuntime()
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)

    bot.submit_event(image_event("img-1"))
    await wait_idle(bot)

    assert len(runtime.image_calls) == 1
    assert "简短说明图片主体" in runtime.image_calls[0][1]
    assert driver.sent == [("A", f"reply:{runtime.image_calls[0][1]}")]
    assert driver.materialized and all(not path.exists() for path in driver.materialized)
    await bot.stop()


@async_test
async def test_private_image_and_text_are_one_ordered_turn(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    runtime = FakeRuntime()
    bot = WechatBot(config(), FakeDriver(), runtime, store, quiet_seconds=0)
    await start_consumer(bot)

    bot.submit_event(image_event("img-1"))
    bot.submit_event(image_event("img-2"))
    bot.submit_event(event("text-1", "A", "比较这两张图"))
    await wait_idle(bot)

    assert runtime.calls == [("A", "比较这两张图")]
    assert len(runtime.image_calls[0][2]) == 2
    assert runtime.image_calls[0][1] == "比较这两张图"
    await bot.stop()


@async_test
async def test_private_text_reference_is_an_independent_fifo_turn(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    runtime = FakeRuntime()
    driver = FakeDriver()
    driver.reference_result = ResolvedReference(
        MessageReference("小明", "预览", "text"),
        "完整原文",
        strategy="located_original",
    )
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0.01)
    await start_consumer(bot)

    bot.submit_event(event("normal", "A", "前一条普通消息"))
    bot.submit_event(reference_event("quote", "A", "这句话是什么意思？"))
    bot.submit_event(event("after", "A", "后一条普通消息"))
    await wait_idle(bot, 0.03)

    assert len(runtime.calls) == 3
    assert runtime.calls[0] == ("A", "前一条普通消息")
    assert "当前问题：这句话是什么意思？" in runtime.calls[1][1]
    assert "被引用者：小明" in runtime.calls[1][1]
    assert "引用内容：完整原文" in runtime.calls[1][1]
    assert runtime.calls[2] == ("A", "后一条普通消息")
    assert runtime.reference_calls == [("A", False), ("A", True), ("A", False)]
    await bot.stop()


@async_test
async def test_private_image_reference_is_multimodal_and_cleans_temp(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    runtime = FakeRuntime()
    driver = FakeDriver()
    source = MessageReference("小明", "[图片]", "image")
    driver.reference_result = ResolvedReference(
        source,
        capture=ImageCapture(Path("placeholder.png"), False),
        strategy="quote_viewer",
    )
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)

    bot.submit_event(
        reference_event("quote-image", "A", "图里是谁？", kind="image")
    )
    await wait_idle(bot)

    assert len(runtime.image_calls) == 1
    assert "当前问题：图里是谁？" in runtime.image_calls[0][1]
    assert runtime.reference_calls == [("A", True)]
    assert driver.materialized and all(not path.exists() for path in driver.materialized)
    await bot.stop()


@async_test
async def test_unsupported_reference_replies_once_without_model(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    driver.reference_result = ResolvedReference(
        MessageReference("小明", "[文件]", "unsupported", "文件"),
        strategy="unsupported",
    )
    runtime = FakeRuntime()
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)

    bot.submit_event(reference_event("quote-file", "A", "看看", kind="unsupported"))
    await wait_idle(bot)

    assert runtime.calls == []
    assert driver.sent == [("A", "当前只支持引用文字和图片。")]
    await bot.stop()


@async_test
async def test_reference_target_recovery_failure_sends_nothing(
    tmp_path: Path,
    caplog,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    driver.reference_result = WechatReferenceTargetError("wrong window")
    runtime = FakeRuntime()
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    caplog.set_level(logging.ERROR, logger="mewcode.wechat")
    await start_consumer(bot)

    bot.submit_event(reference_event("quote", "A", "解释一下"))
    await wait_idle(bot)

    assert runtime.calls == []
    assert driver.sent == []
    assert "strategy=target_recovery status=failure" in caplog.text
    await bot.stop()


@pytest.mark.parametrize(
    ("wechat_config", "private_expected", "group_expected"),
    [
        (config(), True, False),
        (group_config(), False, True),
        (combined_config(), True, True),
    ],
)
def test_reference_startup_privacy_disclosures(
    tmp_path: Path,
    caplog,
    wechat_config: WechatConfig,
    private_expected: bool,
    group_expected: bool,
) -> None:
    logger = logging.getLogger("mewcode.wechat.disclosure")
    bot = WechatBot(
        wechat_config,
        FakeDriver(),
        FakeRuntime(),
        WechatStateStore(tmp_path),
        logger=logger,
    )
    caplog.set_level(logging.WARNING, logger=logger.name)

    bot._log_privacy_disclosures()

    assert ("白名单好友的直接图片和合规引用图片" in caplog.text) is private_expected
    assert ("白名单群中只有满足引用图片" in caplog.text) is group_expected
    assert "非白名单" in caplog.text
    bot._store.close()


@async_test
async def test_reference_logs_do_not_include_message_or_sender_secrets(
    tmp_path: Path,
    caplog,
) -> None:
    secret = "SENSITIVE-QUOTE-DATA"
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    driver.reference_result = ResolvedReference(
        MessageReference("SECRET-SENDER", "SECRET-PREVIEW", "text"),
        secret,
        strategy="preview",
        degraded=True,
    )
    bot = WechatBot(config(), driver, FakeRuntime(), store, quiet_seconds=0)
    caplog.set_level(logging.INFO, logger="mewcode.wechat")
    await start_consumer(bot)

    bot.submit_event(reference_event("quote", "A", "SECRET-QUESTION"))
    await wait_idle(bot)

    assert "status=success" in caplog.text
    assert secret not in caplog.text
    assert "SECRET-SENDER" not in caplog.text
    assert "SECRET-PREVIEW" not in caplog.text
    assert "SECRET-QUESTION" not in caplog.text
    await bot.stop()


@async_test
async def test_five_images_reject_whole_batch_without_model_call(tmp_path: Path) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    runtime = FakeRuntime()
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)
    for index in range(5):
        bot.submit_event(image_event(f"img-{index}"))

    await wait_idle(bot)

    assert runtime.calls == []
    assert driver.materialized == []
    assert driver.sent == [("A", "图片过多或过大，请压缩或分批发送。")]
    await bot.stop()


@async_test
async def test_image_capture_failure_is_not_retried_or_sent_to_model(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    driver.capture_failure = True
    runtime = FakeRuntime()
    bot = WechatBot(config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)

    bot.submit_event(image_event("img-1"))
    await wait_idle(bot)

    assert runtime.calls == []
    assert driver.sent == [("A", "图片暂时没读出来，请重新发送或换一张。")]
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
async def test_group_reference_requires_at_and_image_is_ephemeral(
    tmp_path: Path,
) -> None:
    store = WechatStateStore(tmp_path)
    driver = FakeDriver()
    source = MessageReference("群成员甲", "[图片]", "image")
    driver.reference_result = ResolvedReference(
        source,
        capture=ImageCapture(Path("placeholder.png"), False),
        strategy="located_original_viewer",
    )
    runtime = FakeRuntime()
    bot = WechatBot(group_config(), driver, runtime, store, quiet_seconds=0)
    await start_consumer(bot)

    bot.submit_event(
        group_reference_event(
            "no-at", "张三", "这是谁？", kind="image", is_at=False
        )
    )
    bot.submit_event(
        group_reference_event("with-at", "张三", "这是谁？", kind="image")
    )
    await wait_idle(bot)

    assert len(runtime.group_calls) == 1
    assert len(runtime.image_calls) == 1
    assert runtime.reference_calls == [("测试群聊", True)]
    _, _, _, history = runtime.group_calls[0]
    assert all("data:image" not in item.text for item in history)
    assert any("像素未写入群聊上下文" in item.text for item in history)
    assert driver.group_mentions[0][1] == "张三"
    assert driver.materialized and all(not path.exists() for path in driver.materialized)
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
