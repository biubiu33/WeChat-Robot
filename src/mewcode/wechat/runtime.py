from __future__ import annotations

import asyncio
from pathlib import Path

from mewcode.agent import Agent
from mewcode.config import ProviderConfig
from mewcode.llm import Provider, new_provider
from mewcode.permission import Mode
from mewcode.session.repository import SessionRepository
from mewcode.session.runtime import SessionRuntime
from mewcode.tool import Registry

from .config import WechatConfig
from .store import WechatStateStore


SAFE_ENVIRONMENT = "当前渠道：微信私聊。你没有任何工具，也不能访问本地环境。"


class WechatTurnCancelled(Exception):
    pass


class WechatAgentError(RuntimeError):
    pass


class WechatAgentRuntime:
    def __init__(
        self,
        root: Path,
        provider_config: ProviderConfig,
        config: WechatConfig,
        store: WechatStateStore,
        *,
        provider: Provider | None = None,
    ) -> None:
        self._root = root.resolve()
        self._provider_config = provider_config
        self._config = config
        self._store = store
        self._provider = provider or new_provider(provider_config)
        self._repository = SessionRepository(self._root)

    async def reply(
        self,
        conversation_name: str,
        text: str,
        cancel: asyncio.Event,
    ) -> str:
        runtime = self._open_session(conversation_name)
        try:
            agent = Agent(
                self._provider,
                Registry(),
                context=runtime.context,
                stable_system=self._config.system_prompt,
                environment_supplier=lambda _: SAFE_ENVIRONMENT,
            )
            completion = await asyncio.wait_for(
                agent.run_to_completion(
                    runtime.conversation,
                    text,
                    mode=Mode.DEFAULT,
                    cancel=cancel,
                ),
                timeout=self._config.task_timeout_seconds,
            )
            if completion.cancelled or cancel.is_set():
                raise WechatTurnCancelled
            if completion.error is not None:
                raise WechatAgentError("模型请求失败") from completion.error
            return completion.text.strip()
        finally:
            runtime.close()

    async def close(self) -> None:
        return None

    def _open_session(self, conversation_name: str) -> SessionRuntime:
        session_id = self._store.get_session_id(conversation_name)
        if session_id is not None:
            archive_path = self._repository.paths_for(session_id).archive_path
            if not archive_path.is_file():
                raise WechatAgentError(f"好友 {conversation_name!r} 的会话档案不存在")
            return SessionRuntime.restore(
                self._root,
                session_id,
                self._provider,
                self._provider_config.context_window,
                self._repository.restore(session_id),
                stale=False,
                enable_title=False,
            )

        runtime = SessionRuntime.new(
            self._root,
            self._provider,
            self._provider_config.context_window,
            enable_title=False,
        )
        try:
            self._store.bind_session(conversation_name, runtime.paths.session_id)
        except Exception:
            runtime.close()
            raise
        return runtime


__all__ = [
    "WechatAgentError",
    "WechatAgentRuntime",
    "WechatTurnCancelled",
]
