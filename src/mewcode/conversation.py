from __future__ import annotations

from collections.abc import Callable, Sequence

from .llm import (
    ImageContent,
    ROLE_ASSISTANT,
    ROLE_TOOL,
    ROLE_USER,
    Message,
    ToolCall,
    ToolResult,
)


class Conversation:
    def __init__(
        self,
        messages: Sequence[Message] = (),
        on_append: Callable[[Message], None] | None = None,
    ) -> None:
        self._messages = list(messages)
        self._on_append = on_append

    def add_user(
        self,
        text: str,
        images: Sequence[ImageContent] = (),
    ) -> None:
        self._append(Message(role=ROLE_USER, content=text, images=list(images)))

    def add_assistant(self, text: str) -> None:
        self._append(Message(role=ROLE_ASSISTANT, content=text))

    def add_assistant_with_tool_calls(
        self, text: str, calls: Sequence[ToolCall]
    ) -> None:
        self._append(Message(role=ROLE_ASSISTANT, content=text, tool_calls=list(calls)))

    def add_tool_results(self, results: Sequence[ToolResult]) -> None:
        self._append(Message(role=ROLE_TOOL, tool_results=list(results)))

    def replace_messages(self, messages: Sequence[Message]) -> None:
        """替换仅用于下一次模型请求的上下文，不追加档案事件。"""
        self._messages = list(messages)

    def messages(self) -> list[Message]:
        return list(self._messages)

    def last_role(self) -> str:
        return self._messages[-1].role if self._messages else ""

    def __len__(self) -> int:
        return len(self._messages)

    def _append(self, message: Message) -> None:
        self._messages.append(message)
        if self._on_append is None:
            return
        try:
            self._on_append(message)
        except Exception:
            # 持久化降级不能阻断当前对话。
            pass
