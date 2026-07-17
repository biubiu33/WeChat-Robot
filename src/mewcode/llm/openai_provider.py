from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from mewcode.config import ProviderConfig

from . import (
    Request,
    StreamEvent,
    ToolCall,
    ToolDefinition,
    Usage,
    redact_secret,
)


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
        req: Request,
    ) -> AsyncIterator[StreamEvent]:
        params: dict[str, Any] = {
            "model": self._model,
            "messages": to_openai_messages(req),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if req.tools:
            params["tools"] = to_openai_tools(req.tools)
            params["tool_choice"] = "auto"

        tool_buffers: dict[int, dict[str, str]] = {}
        try:
            stream = await self._client.chat.completions.create(**params)
            async for chunk in stream:
                usage = _extract_usage(chunk)
                if usage is not None:
                    yield StreamEvent(usage=usage)
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


def to_openai_messages(req: Request) -> list[dict[str, Any]]:
    """序列化 OpenAI 消息，稳定提示始终保留在请求前缀。"""
    messages: list[dict[str, Any]] = []
    if req.system.stable:
        messages.append({"role": "system", "content": req.system.stable})
    if req.system.environment:
        messages.append({"role": "system", "content": req.system.environment})
    if req.system.context:
        messages.append({"role": "system", "content": req.system.context})

    for message in req.messages:
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
    if req.reminder:
        messages.append({"role": "user", "content": req.reminder})
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
        buffer = buffers.setdefault(index, {"id": "", "name": "", "arguments": ""})
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


def _extract_usage(chunk: Any) -> Usage | None:
    usage = getattr(chunk, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    details = getattr(usage, "prompt_tokens_details", None)
    cache_read = getattr(details, "cached_tokens", None)
    if not any(
        isinstance(value, int)
        for value in (prompt_tokens, completion_tokens, cache_read)
    ):
        return None
    return Usage(
        input_tokens=prompt_tokens if isinstance(prompt_tokens, int) else 0,
        output_tokens=completion_tokens if isinstance(completion_tokens, int) else 0,
        cache_read=cache_read if isinstance(cache_read, int) else 0,
    )
