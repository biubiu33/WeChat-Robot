"""活动会话的档案、上下文和异步标题生命周期。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.context import ContextController
from mewcode.hook import HookSessionState
from mewcode.conversation import Conversation
from mewcode.llm import Provider
from mewcode.llm.generation import generate_text

from .archive import ArchiveWriter
from .paths import SessionPaths, create_session, paths_for
from .repository import RestoredArchive


class SessionRuntime:
    def __init__(
        self,
        paths: SessionPaths,
        provider: Provider,
        context_window: int,
        *,
        enable_title: bool = True,
    ) -> None:
        self.paths = paths
        self.provider = provider
        self.writer = ArchiveWriter(paths.archive_path)
        self.context = ContextController(
            provider, self.writer, paths.cache_dir, context_window
        )
        self.conversation = Conversation(on_append=self._append)
        self.hook_state = HookSessionState()
        self._title_task: asyncio.Task[None] | None = None
        self._title_started = False
        self._enable_title = enable_title

    @classmethod
    def new(
        cls,
        root: Path,
        provider: Provider,
        context_window: int,
        *,
        enable_title: bool = True,
    ) -> SessionRuntime:
        return cls(
            create_session(root), provider, context_window, enable_title=enable_title
        )

    @classmethod
    def restore(
        cls,
        root: Path,
        session_id: str,
        provider: Provider,
        context_window: int,
        archive: RestoredArchive,
        *,
        stale: bool,
        enable_title: bool = True,
    ) -> SessionRuntime:
        runtime = cls(
            paths_for(root, session_id),
            provider,
            context_window,
            enable_title=enable_title,
        )
        messages = runtime.context.restore(archive)
        runtime.conversation = Conversation(messages, on_append=runtime._append)
        if stale:
            runtime.context.set_staleness_reminder()
        return runtime

    def close(self) -> None:
        if self._title_task is not None and not self._title_task.done():
            self._title_task.cancel()
        self.writer.close()

    def _append(self, message) -> None:
        self.writer.append_message(message, model=self.provider.model)
        if message.role == "user" and self._enable_title and not self._title_started:
            self._title_started = True
            self._title_task = asyncio.create_task(
                self._generate_title(message.content)
            )

    async def _generate_title(self, first_message: str) -> None:
        fallback = " ".join(first_message.split())[:50] or "未命名会话"
        try:
            title = await generate_text(
                self.provider,
                system="你是会话标题生成器。禁止工具调用。只返回简短中文标题。",
                prompt=f"为这条用户消息生成不超过 20 字的标题：{first_message}",
            )
            self.writer.append_title(" ".join(title.split())[:50] or fallback)
        except Exception:
            self.writer.append_title(fallback)
