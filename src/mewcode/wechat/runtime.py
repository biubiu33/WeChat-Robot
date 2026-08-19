from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mewcode.agent import Agent
from mewcode.config import ProviderConfig
from mewcode.llm import Provider, new_provider
from mewcode.llm import Message, ToolCall, ToolResult
from mewcode.permission import Mode
from mewcode.session.repository import SessionRepository
from mewcode.session.runtime import SessionRuntime
from mewcode.tool import Registry
from tzlocal import get_localzone_name

from .config import WechatConfig
from .info.registry import WECHAT_INFO_POLICY, WechatInfoServices, WechatInfoTurn
from .store import WechatStateStore


SAFE_ENVIRONMENT = "当前渠道：微信私聊。你没有任何工具，也不能访问本地环境。"
REDACTED_TOOL_ARGS = "{}"
REDACTED_TOOL_CONTENT = "[微信公共信息工具内容未写入会话档案]"


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
        info_services: WechatInfoServices | None = None,
    ) -> None:
        self._root = root.resolve()
        self._provider_config = provider_config
        self._config = config
        self._store = store
        self._provider = provider or new_provider(provider_config)
        self._repository = SessionRepository(self._root)
        self._info_services = info_services
        if self._info_services is None and config.info_tools.enabled:
            self._info_services = WechatInfoServices(config.info_tools, store)

    async def reply(
        self,
        conversation_name: str,
        text: str,
        cancel: asyncio.Event,
    ) -> str:
        turn = (
            self._info_services.new_turn(conversation_name, text)
            if self._info_services is not None
            else None
        )
        runtime = self._open_session(conversation_name, turn)
        try:
            agent = Agent(
                self._provider,
                turn.registry if turn is not None else Registry(),
                context=runtime.context,
                stable_system=self._stable_system(turn),
                environment_supplier=lambda _: _wechat_environment(turn is not None),
                tool_policy_supplier=(
                    lambda: (
                        frozenset(
                            {
                                "get_current_time",
                                "web_search",
                                "web_fetch",
                                "get_weather",
                            }
                        )
                        if turn is not None
                        else None
                    )
                ),
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
            reply = completion.text.strip()
            return turn.finalize_reply(reply) if turn is not None else reply
        finally:
            runtime.close()

    async def close(self) -> None:
        if self._info_services is not None:
            await self._info_services.close()

    def _open_session(
        self, conversation_name: str, turn: WechatInfoTurn | None
    ) -> SessionRuntime:
        archive_transform = (
            (lambda message: _wechat_archive_message(message, turn))
            if turn is not None
            else None
        )
        restore_filter = _wechat_history_messages if turn is not None else None
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
                archive_message_transform=archive_transform,
                restore_message_filter=restore_filter,
                transient_tool_results=turn is not None,
            )

        runtime = SessionRuntime.new(
            self._root,
            self._provider,
            self._provider_config.context_window,
            enable_title=False,
            archive_message_transform=archive_transform,
            restore_message_filter=restore_filter,
            transient_tool_results=turn is not None,
        )
        try:
            self._store.bind_session(conversation_name, runtime.paths.session_id)
        except Exception:
            runtime.close()
            raise
        return runtime

    def _stable_system(self, turn: WechatInfoTurn | None) -> str:
        if turn is None:
            return self._config.system_prompt
        return f"{self._config.system_prompt}\n\n{WECHAT_INFO_POLICY}"


def _wechat_environment(tools_enabled: bool) -> str:
    timezone_name = get_localzone_name()
    now = datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")
    capability = (
        "仅可使用已列出的四个只读公共信息工具；不能访问本地环境。"
        if tools_enabled
        else "你没有任何工具，也不能访问本地环境。"
    )
    return (
        f"当前渠道：微信私聊。{capability}\n"
        f"本机当前日期时间：{now}\n本机 IANA 时区：{timezone_name}"
    )


def _wechat_archive_message(message: Message, turn: WechatInfoTurn) -> Message:
    if message.role == "assistant" and message.tool_calls:
        return Message(
            "assistant",
            REDACTED_TOOL_CONTENT,
            [
                ToolCall(call.id, call.name, REDACTED_TOOL_ARGS)
                for call in message.tool_calls
            ],
            [],
        )
    if message.role == "tool":
        return Message(
            "tool",
            REDACTED_TOOL_CONTENT,
            [],
            [
                ToolResult(result.tool_call_id, REDACTED_TOOL_CONTENT, result.is_error)
                for result in message.tool_results
            ],
        )
    if message.role == "assistant":
        return Message("assistant", turn.finalize_reply(message.content))
    return message


def _wechat_history_messages(messages: list[Message]) -> list[Message]:
    return [
        message
        for message in messages
        if message.role == "user"
        or (message.role == "assistant" and not message.tool_calls)
    ]


__all__ = [
    "WechatAgentError",
    "WechatAgentRuntime",
    "WechatTurnCancelled",
    "_wechat_archive_message",
    "_wechat_environment",
    "_wechat_history_messages",
]
