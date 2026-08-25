from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from .config import WechatConfig
from .models import (
    GroupHistoryItem,
    PendingBatch,
    QueuedBatch,
    WechatDesktopEvent,
    WechatReply,
)
from .runtime import WechatAgentRuntime, WechatTurnCancelled, _chat_delay
from .store import WechatStateStore
from .uia_driver import WechatUiaDriver


@dataclass
class ActiveTurn:
    conversation_name: str
    cancel: asyncio.Event
    delivered: list[str] = field(default_factory=list)
    private: bool = True
    mentioned: bool = False


class WechatBot:
    def __init__(
        self,
        config: WechatConfig,
        driver: WechatUiaDriver,
        runtime: WechatAgentRuntime,
        store: WechatStateStore,
        *,
        logger: logging.Logger | None = None,
        quiet_seconds: float = 7.0,
    ) -> None:
        self._config = config
        self._driver = driver
        self._runtime = runtime
        self._store = store
        self._logger = logger or logging.getLogger("mewcode.wechat")
        self._quiet_seconds = max(0.0, quiet_seconds)
        self._queue: asyncio.Queue[QueuedBatch | None] = asyncio.Queue()
        self._pending: dict[str | tuple[str, str], PendingBatch] = {}
        self._allowed = frozenset(config.allowed_contacts)
        self._allowed_groups = frozenset(config.allowed_groups)
        self._self_name = config.self_names[0] if config.self_names else "机器人"
        self._group_history: dict[str, deque[GroupHistoryItem]] = {}
        self._group_context_seen: dict[str, set[str]] = {}
        self._thread_stop = threading.Event()
        self._observer: threading.Thread | None = None
        self._consumer: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopped = asyncio.Event()
        self._active: ActiveTurn | None = None
        self._closing = False

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(self._driver.establish_baseline)
        await asyncio.to_thread(self._driver.start)
        self._consumer = asyncio.create_task(
            self._consume(), name="mewcode-wechat-fifo"
        )
        self._observer = threading.Thread(
            target=self._observe,
            name="mewcode-wechat-observer",
            daemon=True,
        )
        self._observer.start()
        self._logger.info("微信机器人已进入监听状态")
        try:
            await self._stopped.wait()
        finally:
            await self.stop()

    async def stop(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._thread_stop.set()
        if self._active is not None:
            self._active.cancel.set()
        timers = [
            pending.timer
            for pending in self._pending.values()
            if pending.timer is not None and not pending.timer.done()
        ]
        for timer in timers:
            timer.cancel()
        if timers:
            await asyncio.gather(*timers, return_exceptions=True)
        self._pending.clear()
        await asyncio.to_thread(self._driver.close)
        if self._observer and self._observer.is_alive():
            await asyncio.to_thread(self._observer.join, 3.0)
        if self._consumer is not None and not self._consumer.done():
            await self._queue.put(None)
            await self._consumer
        await self._runtime.close()
        await asyncio.to_thread(self._store.close)
        self._stopped.set()
        self._logger.info("微信机器人已停止")

    def submit_event(self, event: WechatDesktopEvent) -> bool:
        if self._closing:
            return False
        if not event.incoming:
            return False
        allowed = (
            event.conversation_name in self._allowed
            if event.private
            else event.conversation_name in self._allowed_groups
        )
        if not allowed:
            self._logger.info("忽略非白名单微信会话")
            return False
        if not event.private:
            self._append_group_history(
                event.conversation_name,
                GroupHistoryItem(
                    event.event_id,
                    event.sender_name,
                    event.raw_text or event.text,
                ),
            )
            if not event.is_at:
                return True
        if not self._store.record_event_once(event):
            self._logger.info("忽略重复微信事件")
            return False

        active = self._active
        if (
            event.private
            and active is not None
            and active.private
            and active.conversation_name == event.conversation_name
        ):
            active.cancel.set()

        batch_key = self._batch_key(event)
        pending = self._pending.get(batch_key)
        if pending is None:
            pending = PendingBatch([event], revision=1)
            self._pending[batch_key] = pending
        else:
            if pending.timer is not None and not pending.timer.done():
                pending.timer.cancel()
            pending.events.append(event)
            pending.revision += 1
            pending.queued = False
        pending.timer = asyncio.create_task(
            self._enqueue_after_quiet(batch_key, pending.revision),
            name=f"mewcode-wechat-quiet-{event.conversation_name}-{event.sender_name}",
        )
        return True

    @staticmethod
    def _batch_key(event: WechatDesktopEvent) -> str | tuple[str, str]:
        return (
            event.conversation_name
            if event.private
            else (event.conversation_name, event.sender_name)
        )

    def _observe(self) -> None:
        assert self._loop is not None
        while not self._thread_stop.is_set():
            try:
                events = self._driver.wait_for_events(self._thread_stop)
                for event in events:
                    self._loop.call_soon_threadsafe(self.submit_event, event)
            except Exception as exc:  # noqa: BLE001 - isolate the desktop observer loop
                self._logger.error("微信 UIA 观察失败: %s: %s", type(exc).__name__, exc)
                self._thread_stop.wait(2.0)

    async def _enqueue_after_quiet(
        self,
        batch_key: str | tuple[str, str],
        revision: int,
    ) -> None:
        try:
            await asyncio.sleep(self._quiet_seconds)
        except asyncio.CancelledError:
            return
        if self._closing:
            return
        pending = self._pending.get(batch_key)
        if pending is None or pending.revision != revision:
            return
        pending.timer = None
        pending.queued = True
        event = pending.events[-1]
        history = tuple(self._group_history.get(event.conversation_name, ()))
        if not event.private:
            # A completed group quiet window is immutable. Removing it here lets
            # a later @ from the same member open a fresh window while this batch
            # waits behind an active reply in the global FIFO.
            del self._pending[batch_key]
        await self._queue.put(
            QueuedBatch(
                event.conversation_name,
                tuple(pending.events),
                revision,
                time.time(),
                sender_name=event.sender_name,
                private=event.private,
                group_history=history if not event.private else (),
            )
        )

    def _claim(self, queued: QueuedBatch) -> bool:
        if not queued.private:
            return True
        batch_key = self._batch_key(queued.events[-1])
        pending = self._pending.get(batch_key)
        if pending is None or not pending.queued or pending.revision != queued.revision:
            return False
        del self._pending[batch_key]
        return True

    async def _consume(self) -> None:
        while True:
            queued = await self._queue.get()
            if queued is None:
                self._queue.task_done()
                return
            if self._closing or not self._claim(queued):
                self._queue.task_done()
                continue

            event = queued.events[-1]
            active = ActiveTurn(
                queued.conversation_name,
                asyncio.Event(),
                private=queued.private,
            )
            self._active = active

            async def on_tool_stage(
                status: str,
                target: WechatDesktopEvent = event,
                turn: ActiveTurn = active,
            ) -> None:
                await self._send_one(target, status, turn)

            try:
                if queued.private:
                    reply = await self._runtime.reply(
                        queued.conversation_name,
                        queued.text,
                        active.cancel,
                        on_tool_stage,
                    )
                else:
                    reply_group = getattr(self._runtime, "reply_group", None)
                    if callable(reply_group):
                        reply = await reply_group(
                            queued.conversation_name,
                            queued.sender_name,
                            queued.text,
                            queued.group_history,
                            active.cancel,
                            on_tool_stage,
                        )
                    else:
                        reply = await self._runtime.reply(
                            queued.conversation_name,
                            queued.text,
                            active.cancel,
                            on_tool_stage,
                        )
                if not active.cancel.is_set():
                    await self._send_reply(event, reply, active)
            except WechatTurnCancelled:
                pass
            except TimeoutError:
                if not active.cancel.is_set():
                    await self._try_send_error(event, "处理超时，请稍后再试。", active)
            except Exception as exc:  # noqa: BLE001 - preserve the queue consumer
                self._logger.error("微信消息处理失败: %s", type(exc).__name__)
                if not active.cancel.is_set():
                    await self._try_send_error(event, "处理失败，请稍后再试。", active)
            finally:
                try:
                    if queued.private:
                        self._runtime.record_delivery(
                            queued.conversation_name,
                            active.delivered,
                        )
                except Exception as exc:  # noqa: BLE001 - delivery history is best-effort
                    self._logger.error("微信投递历史保存失败: %s", type(exc).__name__)
                self._active = None
                for item in queued.events:
                    self._store.mark_processed(item.event_id)
                self._queue.task_done()

    async def _try_send_error(
        self,
        event: WechatDesktopEvent,
        text: str,
        active: ActiveTurn,
    ) -> None:
        try:
            await self._send_one(event, text, active)
        except Exception as exc:  # noqa: BLE001 - UIA failures must not stop the bot
            self._logger.error("微信回复发送失败: %s", type(exc).__name__)

    async def _send_reply(
        self,
        event: WechatDesktopEvent,
        reply: WechatReply,
        active: ActiveTurn,
    ) -> None:
        seconds_per_char = random.uniform(0.035, 0.055)
        try:
            for index, message in enumerate(reply.messages):
                if active.cancel.is_set():
                    return
                if (
                    reply.chat
                    and index
                    and not await self._wait_or_cancel(
                        active.cancel,
                        _chat_delay(message, seconds_per_char),
                    )
                ):
                    return
                await self._send_one(event, message, active)
            if reply.source_message and not active.cancel.is_set():
                await self._send_one(event, reply.source_message, active)
        except Exception as exc:  # noqa: BLE001 - stop this reply batch on send failure
            self._logger.error("微信回复发送失败: %s", type(exc).__name__)

    @staticmethod
    async def _wait_or_cancel(cancel: asyncio.Event, delay: float) -> bool:
        try:
            await asyncio.wait_for(cancel.wait(), timeout=delay)
        except TimeoutError:
            return True
        return False

    async def _send_one(
        self,
        event: WechatDesktopEvent,
        text: str,
        active: ActiveTurn,
    ) -> None:
        if active.cancel.is_set() or not text:
            return
        if not event.private and not active.mentioned:
            sender = event.sender_name
            send_group_first = getattr(self._driver, "send_group_first", None)
            if callable(send_group_first):
                real, reason = await asyncio.to_thread(
                    send_group_first,
                    event,
                    sender,
                    text,
                )
                if not real:
                    self._logger.warning(
                        "微信群 @ 已降级为文本: group=%s sender=%s reason=%s",
                        event.conversation_name,
                        sender,
                        reason or "成员菜单无法唯一匹配",
                    )
            else:
                await asyncio.to_thread(
                    self._driver.send_text,
                    event,
                    f"@{sender}\n{text}",
                )
            active.mentioned = True
        else:
            await asyncio.to_thread(self._driver.send_text, event, text)
        active.delivered.append(text)
        if not event.private:
            self._append_group_history(
                event.conversation_name,
                GroupHistoryItem(
                    f"outgoing:{time.time_ns()}",
                    self._self_name,
                    text,
                ),
            )

    def _append_group_history(
        self,
        conversation_name: str,
        item: GroupHistoryItem,
    ) -> None:
        history = self._group_history.setdefault(conversation_name, deque(maxlen=20))
        seen = self._group_context_seen.setdefault(conversation_name, set())
        if item.message_key in seen:
            return
        if len(history) == history.maxlen and history:
            seen.discard(history[0].message_key)
        history.append(item)
        seen.add(item.message_key)


__all__ = ["ActiveTurn", "WechatBot"]
