from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from mewcode.config import ProviderConfig
from mewcode.prompt import SYSTEM_PROMPT

from . import Message, StreamEvent, redact_secret


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

    async def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]:
        messages = [{"role": msg.role, "content": msg.content} for msg in msgs]
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": messages,
        }
        if self._thinking:
            params["thinking"] = {"type": "enabled", "budget_tokens": 2048}

        try:
            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    text = _extract_text_delta(event)
                    if text:
                        yield StreamEvent(text=text)
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(err=RuntimeError(redact_secret(str(exc), self._api_key)))


def _extract_text_delta(event: Any) -> str:
    if getattr(event, "type", None) != "content_block_delta":
        return ""

    delta = getattr(event, "delta", None)
    if getattr(delta, "type", None) != "text_delta":
        return ""

    text = getattr(delta, "text", "")
    return text if isinstance(text, str) else ""
