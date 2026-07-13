from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from mewcode.config import ProviderConfig
from mewcode.prompt import SYSTEM_PROMPT

from . import Message, StreamEvent, ToolCall, ToolDefinition, redact_secret


class AnthropicProvider:
    def __init__(self, cfg: ProviderConfig) -> None:
        import anthropic

        kwargs: dict[str, Any] = {"api_key": cfg.api_key}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        self._client = anthropic.AsyncAnthropic(**kwargs)
        self._api_key = cfg.api_key
        self._name = cfg.name
        self._model = cfg.model
        self._thinking = cfg.thinking

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    def redact(self, text: str) -> str:
        return redact_secret(text, self._api_key)

    async def stream(
        self,
        msgs: list[Message],
        tools: list[ToolDefinition],
    ) -> AsyncIterator[StreamEvent]:
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": to_anthropic_messages(msgs),
        }
        if tools:
            params["tools"] = to_anthropic_tools(tools)
        if self._thinking and not _has_tool_history(msgs):
            params["thinking"] = {"type": "enabled", "budget_tokens": 2048}

        try:
            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    text = _extract_text_delta(event)
                    if text:
                        yield StreamEvent(text=text)
                final_message = await stream.get_final_message()
            calls = _extract_tool_calls(final_message)
            if calls:
                yield StreamEvent(tool_calls=calls)
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(err=RuntimeError(self.redact(str(exc))))


def _extract_text_delta(event: Any) -> str:
    if getattr(event, "type", None) != "content_block_delta":
        return ""

    delta = getattr(event, "delta", None)
    if getattr(delta, "type", None) != "text_delta":
        return ""

    text = getattr(delta, "text", "")
    return text if isinstance(text, str) else ""


def to_anthropic_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]


def to_anthropic_messages(msgs: list[Message]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in msgs:
        if message.role == "assistant" and message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                try:
                    input_value = json.loads(call.input or "{}")
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"工具 {call.name} 参数不是有效 JSON: {exc.msg}"
                    ) from exc
                if not isinstance(input_value, dict):
                    raise ValueError(f"工具 {call.name} 参数必须是 JSON 对象")
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": input_value,
                    }
                )
            messages.append({"role": "assistant", "content": blocks})
        elif message.role == "tool":
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.tool_call_id,
                            "content": result.content,
                            "is_error": result.is_error,
                        }
                        for result in message.tool_results
                    ],
                }
            )
        else:
            messages.append({"role": message.role, "content": message.content})
    return messages


def _extract_tool_calls(final_message: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for block in getattr(final_message, "content", None) or []:
        if getattr(block, "type", None) != "tool_use":
            continue
        input_value = getattr(block, "input", {})
        calls.append(
            ToolCall(
                id=str(getattr(block, "id", "")),
                name=str(getattr(block, "name", "")),
                input=json.dumps(input_value, ensure_ascii=False),
            )
        )
    return calls


def _has_tool_history(msgs: list[Message]) -> bool:
    return any(message.tool_calls or message.tool_results for message in msgs)
