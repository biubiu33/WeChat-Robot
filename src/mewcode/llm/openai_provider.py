from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from mewcode.config import ProviderConfig
from mewcode.prompt import SYSTEM_PROMPT

from . import Message, StreamEvent, redact_secret


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

    async def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend({"role": msg.role, "content": msg.content} for msg in msgs)

        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
            )
            async for chunk in stream:
                text = _extract_text_delta(chunk)
                if text:
                    yield StreamEvent(text=text)
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(err=RuntimeError(redact_secret(str(exc), self._api_key)))


def _extract_text_delta(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None)
    if not choices:
        return ""

    delta = getattr(choices[0], "delta", None)
    text = getattr(delta, "content", "")
    return text if isinstance(text, str) else ""
