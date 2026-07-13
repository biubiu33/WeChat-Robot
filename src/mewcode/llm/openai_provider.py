from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from mewcode.config import ProviderConfig
from mewcode.prompt import SYSTEM_PROMPT

from . import Message, StreamEvent, ToolCall, ToolDefinition, redact_secret


class OpenAIProvider:
    def __init__(self, cfg: ProviderConfig) -> None:
        import openai

        kwargs: dict[str, Any] = {"api_key": cfg.api_key}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        self._client = openai.AsyncOpenAI(**kwargs)
        self._api_key = cfg.api_key
        self._name = cfg.name
        self._model = cfg.model

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
            "messages": to_openai_messages(msgs),
            "stream": True,
        }
        if tools:
            params["tools"] = to_openai_tools(tools)
            params["tool_choice"] = "auto"

        tool_buffers: dict[int, dict[str, str]] = {}
        try:
            stream = await self._client.chat.completions.create(**params)
            async for chunk in stream:
                text = _extract_text_delta(chunk)
                if text:
                    yield StreamEvent(text=text)
                _accumulate_tool_call_deltas(chunk, tool_buffers)
            calls = _build_tool_calls(tool_buffers)
            if calls:
                yield StreamEvent(tool_calls=calls)
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(err=RuntimeError(self.redact(str(exc))))


def _extract_text_delta(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return ""

    delta = getattr(choices[0], "delta", None)
    text = getattr(delta, "content", "")
    return text if isinstance(text, str) else ""


def to_openai_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def to_openai_messages(msgs: list[Message]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    for message in msgs:
        if message.role == "assistant" and message.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": call.input or "{}",
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
        elif message.role == "tool":
            messages.extend(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.content,
                }
                for result in message.tool_results
            )
        else:
            messages.append({"role": message.role, "content": message.content})
    return messages


def _accumulate_tool_call_deltas(
    chunk: Any,
    buffers: dict[int, dict[str, str]],
) -> None:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return
    delta = getattr(choices[0], "delta", None)
    for item in getattr(delta, "tool_calls", None) or []:
        index = getattr(item, "index", None)
        if not isinstance(index, int):
            continue
        buffer = buffers.setdefault(
            index, {"id": "", "name": "", "arguments": ""}
        )
        call_id = getattr(item, "id", None)
        if isinstance(call_id, str) and call_id:
            buffer["id"] = call_id
        function = getattr(item, "function", None)
        name = getattr(function, "name", None)
        arguments = getattr(function, "arguments", None)
        if isinstance(name, str):
            buffer["name"] += name
        if isinstance(arguments, str):
            buffer["arguments"] += arguments


def _build_tool_calls(buffers: dict[int, dict[str, str]]) -> list[ToolCall]:
    return [
        ToolCall(
            id=buffer["id"],
            name=buffer["name"],
            input=buffer["arguments"] or "{}",
        )
        for _, buffer in sorted(buffers.items())
    ]
