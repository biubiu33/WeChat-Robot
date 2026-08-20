from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tzlocal import get_localzone_name

from mewcode.agent import NOTICE_CANCELLED, Agent, Completion, Phase
from mewcode.config import ProviderConfig
from mewcode.llm import Message, Provider, ToolCall, ToolResult, new_provider
from mewcode.permission import Mode
from mewcode.session.archive import ArchiveWriter
from mewcode.session.repository import SessionRepository
from mewcode.session.runtime import SessionRuntime
from mewcode.tool import Registry

from .config import WechatConfig
from .info.registry import WECHAT_INFO_POLICY, WechatInfoServices, WechatInfoTurn
from .models import WechatReply
from .store import WechatStateStore

SAFE_ENVIRONMENT = "当前渠道：微信私聊。你没有任何工具，也不能访问本地环境。"
REDACTED_TOOL_ARGS = "{}"
REDACTED_TOOL_CONTENT = "[微信公共信息工具内容未写入会话档案]"
BUBBLE_DELIMITER = "<|bubble|>"
MAX_CHAT_BUBBLES = 7

WECHAT_REPLY_POLICY = f"""
你正在微信私聊中回复好友。先根据当前消息和本好友的对话上下文，选择自然闲聊表达或专业回答表达，不要额外说明你的分类过程。

日常闲聊应简短、口语化并直接回应当前语境。避免机械复述，避免固定使用“当然可以”“希望对你有所帮助”“有需要随时找我”等套话，不要无缘无故展开成长说明、强行开启新话题或主动发出邀请。
闲聊需要连续发送多个语义气泡时，在气泡之间只输出分隔标记 {BUBBLE_DELIMITER}。通常使用一至三个气泡，确有自然表达需要时最多七个。单个短回应不需要分隔标记。

专业知识、步骤说明、代码、资料整理和工具结果应使用完整、清楚的纯文本段落，不得使用 {BUBBLE_DELIMITER}。可以使用普通空行和自然的中文编号。
所有回答都不要使用 Markdown 包装：不要使用星号加粗或斜体、Markdown 标题、引用符号、Markdown 链接或三反引号代码围栏。代码直接原样输出并保留缩进和代码字符。
工具进度由宿主程序另行告知好友；不要在最终回答中重复“我正在调用工具”之类的过程提示。
被问及身份时如实说明你是 AI 助手，不要伪装成人类；现有安全和权限边界始终有效。

闲聊多气泡示例：
今天有点累{BUBBLE_DELIMITER}不过看到你的消息好多了

闲聊单气泡示例：
哈哈，这个确实有点离谱

专业说明示例：
这件事主要有两个原因：

一、输入数据不完整。
二、当前条件互相冲突。

代码回答示例：
def greet(name):
    return f"你好，{{name}}"
""".strip()

_FENCE_RE = re.compile(r"^\s*`{3}[^\n]*\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}#{2,6}\s+")
_QUOTE_RE = re.compile(r"^\s{0,3}>\s?")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_BOLD_RE = re.compile(r"(?<!\*)\*\*(\S(?:.*?\S)?)\*\*(?!\*)")
_UNDERLINE_BOLD_RE = re.compile(r"(?<![\w_])__(\S(?:.*?\S)?)__(?![\w_])")
_ITALIC_RE = re.compile(r"(?<!\*)\*(\S(?:.*?\S)?)\*(?!\*)")
_UNDERLINE_ITALIC_RE = re.compile(r"(?<![\w_])_(\S(?:.*?\S)?)_(?![\w_])")
_INLINE_CODE_RE = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_BREAK_RE = re.compile(r"[。！？；.!?;]\s*")

_TOOL_STAGES = {
    "get_current_time": ("time", "我看一下时间。"),
    "web_search": ("web", "我查一下相关资料。"),
    "web_fetch": ("web", "我查一下相关资料。"),
}


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
        on_tool_stage: Callable[[str], Awaitable[None]] | None = None,
    ) -> WechatReply:
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
                            }
                        )
                        if turn is not None
                        else None
                    )
                ),
            )
            completion, used_web = await asyncio.wait_for(
                self._run_agent(
                    agent,
                    runtime,
                    text,
                    cancel,
                    on_tool_stage,
                ),
                timeout=self._config.task_timeout_seconds,
            )
            if completion.cancelled or cancel.is_set():
                raise WechatTurnCancelled
            if completion.error is not None:
                raise WechatAgentError("模型请求失败") from completion.error

            answer = completion.text.strip()
            source_message = ""
            if turn is not None:
                finalized = turn.finalize_reply(answer)
                answer = finalized.answer
                source_message = finalized.source_message
            return _build_wechat_reply(
                answer,
                max_chars=self._config.max_reply_chars,
                source_message=source_message,
                force_professional=used_web,
            )
        finally:
            runtime.close()

    def record_delivery(
        self,
        conversation_name: str,
        messages: Sequence[str],
    ) -> None:
        delivered = [message.strip() for message in messages if message.strip()]
        if not delivered:
            return
        session_id = self._store.get_session_id(conversation_name)
        if session_id is None:
            return
        archive_path = self._repository.paths_for(session_id).archive_path
        writer = ArchiveWriter(archive_path)
        try:
            writer.append_message(Message("assistant", "\n\n".join(delivered)))
        finally:
            writer.close()

    async def close(self) -> None:
        if self._info_services is not None:
            await self._info_services.close()

    async def _run_agent(
        self,
        agent: Agent,
        runtime: SessionRuntime,
        text: str,
        cancel: asyncio.Event,
        on_tool_stage: Callable[[str], Awaitable[None]] | None,
    ) -> tuple[Completion, bool]:
        runtime.conversation.add_user(text)
        error: Exception | None = None
        cancelled = False
        used_web = False
        notified: set[str] = set()

        async for event in agent.run(
            runtime.conversation,
            mode=Mode.DEFAULT,
            cancel=cancel,
        ):
            if event.err is not None:
                error = event.err
            if event.notice == NOTICE_CANCELLED:
                cancelled = True
            if event.tool is None or event.tool.phase is not Phase.START:
                continue
            stage = _TOOL_STAGES.get(event.tool.name)
            if stage is None:
                continue
            stage_name, status = stage
            used_web = used_web or stage_name == "web"
            if stage_name in notified:
                continue
            notified.add(stage_name)
            if on_tool_stage is not None and not cancel.is_set():
                await on_tool_stage(status)

        content = runtime.conversation.messages()[-1].content
        return Completion(content, cancelled=cancelled, error=error), used_web

    def _open_session(
        self, conversation_name: str, turn: WechatInfoTurn | None
    ) -> SessionRuntime:
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
                archive_message_transform=_wechat_archive_message,
                restore_message_filter=_wechat_history_messages,
                transient_tool_results=turn is not None,
            )

        runtime = SessionRuntime.new(
            self._root,
            self._provider,
            self._provider_config.context_window,
            enable_title=False,
            archive_message_transform=_wechat_archive_message,
            restore_message_filter=_wechat_history_messages,
            transient_tool_results=turn is not None,
        )
        try:
            self._store.bind_session(conversation_name, runtime.paths.session_id)
        except Exception:
            runtime.close()
            raise
        return runtime

    def _stable_system(self, turn: WechatInfoTurn | None) -> str:
        parts = [self._config.system_prompt, WECHAT_REPLY_POLICY]
        if turn is not None:
            parts.append(WECHAT_INFO_POLICY)
        return "\n\n".join(parts)


def _wechat_environment(tools_enabled: bool) -> str:
    timezone_name = get_localzone_name()
    now = datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")
    capability = (
        "仅可使用已列出的三个只读公共信息工具；不能访问本地环境。"
        if tools_enabled
        else "你没有任何工具，也不能访问本地环境。"
    )
    return (
        f"当前渠道：微信私聊。{capability}\n"
        f"本机当前日期时间：{now}\n本机 IANA 时区：{timezone_name}"
    )


def _wechat_archive_message(message: Message) -> Message | None:
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
        return None
    return message


def _wechat_history_messages(messages: list[Message]) -> list[Message]:
    return [
        message
        for message in messages
        if message.role == "user"
        or (message.role == "assistant" and not message.tool_calls)
    ]


def _to_wechat_plain_text(text: str) -> str:
    lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.fullmatch(line):
            in_fence = not in_fence
            continue
        if in_fence:
            lines.append(line)
            continue
        line = _HEADING_RE.sub("", line)
        line = _QUOTE_RE.sub("", line)
        line = _LINK_RE.sub(lambda match: f"{match.group(1)}：{match.group(2)}", line)
        line = _BOLD_RE.sub(r"\1", line)
        line = _UNDERLINE_BOLD_RE.sub(r"\1", line)
        line = _ITALIC_RE.sub(r"\1", line)
        line = _UNDERLINE_ITALIC_RE.sub(r"\1", line)
        line = _INLINE_CODE_RE.sub(r"\1", line)
        lines.append(line.rstrip())
    result = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", result)


def _build_wechat_reply(
    text: str,
    *,
    max_chars: int,
    source_message: str = "",
    force_professional: bool = False,
) -> WechatReply:
    source = _to_wechat_plain_text(source_message)
    if BUBBLE_DELIMITER in text and not force_professional:
        bubbles = [
            clean
            for part in text.split(BUBBLE_DELIMITER)
            if (clean := _to_wechat_plain_text(part))
        ]
        if len(bubbles) > MAX_CHAT_BUBBLES:
            bubbles = bubbles[: MAX_CHAT_BUBBLES - 1] + [
                "\n".join(bubbles[MAX_CHAT_BUBBLES - 1 :])
            ]
        if any(len(bubble) > max_chars for bubble in bubbles):
            professional = "\n".join(bubbles)
            return WechatReply(
                _split_professional_text(professional, max_chars),
                False,
                source,
            )
        return WechatReply(tuple(bubbles), True, source)

    professional = _to_wechat_plain_text(text.replace(BUBBLE_DELIMITER, "\n"))
    return WechatReply(
        _split_professional_text(professional, max_chars),
        False,
        source,
    )


def _split_professional_text(text: str, max_chars: int) -> tuple[str, ...]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    remaining = text.strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining)
            break
        window = remaining[:max_chars]
        candidates = [window.rfind("\n\n"), window.rfind("\n")]
        candidates.extend(match.end() for match in _BREAK_RE.finditer(window))
        usable = [position for position in candidates if position >= max_chars // 3]
        split_at = max(usable, default=max_chars)
        chunk = remaining[:split_at].strip()
        if not chunk:
            split_at = max_chars
            chunk = remaining[:split_at]
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip("\n")
    return tuple(chunks)


def _chat_delay(next_text: str, seconds_per_char: float) -> float:
    return min(2.0, max(0.4, 0.25 + len(next_text) * seconds_per_char))


__all__ = [
    "BUBBLE_DELIMITER",
    "WECHAT_REPLY_POLICY",
    "WechatAgentError",
    "WechatAgentRuntime",
    "WechatTurnCancelled",
    "_build_wechat_reply",
    "_chat_delay",
    "_split_professional_text",
    "_to_wechat_plain_text",
    "_wechat_archive_message",
    "_wechat_environment",
    "_wechat_history_messages",
]
