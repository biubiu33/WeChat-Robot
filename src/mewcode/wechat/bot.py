from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass

from .config import WechatConfig
from .models import QueuedMessage, WechatDesktopEvent
from .runtime import WechatAgentRuntime, WechatTurnCancelled
from .store import WechatStateStore
from .uia_driver import WechatUiaDriver


@dataclass
class ActiveTurn:
    conversation_name: str
    cancel: asyncio.Event


class WechatBot:
    def __init__(
        self,
        config: WechatConfig,
        driver: WechatUiaDriver,
        runtime: WechatAgentRuntime,
        store: WechatStateStore,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._driver = driver
        self._runtime = runtime
        self._store = store
        self._logger = logger or logging.getLogger("mewcode.wechat")
        self._queue: asyncio.Queue[QueuedMessage | None] = asyncio.Queue()
        self._allowed = frozenset(config.allowed_contacts)
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
        if not event.incoming or not event.private:
            return False
        if event.conversation_name not in self._allowed:
            self._logger.info("忽略非白名单微信会话")
            return False
        if not self._store.record_event_once(event):
            self._logger.info("忽略重复微信事件")
            return False
        if event.text.strip() == "/cancel":
            asyncio.create_task(self._handle_cancel(event))
            return True
        self._queue.put_nowait(QueuedMessage(event, time.time()))
        return True

    def _observe(self) -> None:
        assert self._loop is not None
        while not self._thread_stop.is_set():
            try:
                events = self._driver.wait_for_events(self._thread_stop)
                for event in events:
                    self._loop.call_soon_threadsafe(self.submit_event, event)
            except Exception as exc:
                self._logger.error("微信 UIA 观察失败: %s", type(exc).__name__)
                self._thread_stop.wait(2.0)

    async def _consume(self) -> None:
        while True:
            queued = await self._queue.get()
            if queued is None:
                self._queue.task_done()
                return
            event = queued.event
            cancel = asyncio.Event()
            self._active = ActiveTurn(event.conversation_name, cancel)
            try:
                reply = await self._runtime.reply(
                    event.conversation_name, event.text, cancel
                )
                if reply and not cancel.is_set():
                    await self._try_send_chunks(event, reply)
            except WechatTurnCancelled:
                pass
            except TimeoutError:
                await self._try_send_chunks(event, "处理超时，请稍后再试。")
            except Exception as exc:
                self._logger.error("微信消息处理失败: %s", type(exc).__name__)
                await self._try_send_chunks(event, "处理失败，请稍后再试。")
            finally:
                self._active = None
                self._store.mark_processed(event.event_id)
                self._queue.task_done()

    async def _handle_cancel(self, event: WechatDesktopEvent) -> None:
        active = self._active
        if active is not None and active.conversation_name == event.conversation_name:
            active.cancel.set()
            text = "已取消当前任务。"
        else:
            text = "当前没有可取消的任务。"
        try:
            await self._try_send_chunks(event, text)
        finally:
            self._store.mark_processed(event.event_id)

    async def _try_send_chunks(self, event: WechatDesktopEvent, text: str) -> None:
        try:
            await self._send_chunks(event, text)
        except Exception as exc:
            self._logger.error("微信回复发送失败: %s", type(exc).__name__)

    async def _send_chunks(self, event: WechatDesktopEvent, text: str) -> None:
        chunks = [
            text[index : index + self._config.max_reply_chars]
            for index in range(0, len(text), self._config.max_reply_chars)
        ]
        for chunk in chunks:
            await asyncio.to_thread(self._driver.send_text, event, chunk)


__all__ = ["ActiveTurn", "WechatBot"]
