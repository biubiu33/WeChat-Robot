from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

import httpx

from mewcode.errors import ProviderError, StreamProtocolError
from mewcode.http import create_http_client
from mewcode.models import ChatMessage, ProviderProfile, StreamChunk
from mewcode.providers.base import redact_secret
from mewcode.sse import iter_sse_events


class OpenAIProvider:
    def __init__(
        self, profile: ProviderProfile, client: httpx.Client | None = None
    ) -> None:
        self.profile = profile
        self.client = client or create_http_client()

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[StreamChunk]:
        payload = {
            "model": self.profile.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self.profile.api_key}",
            "Content-Type": "application/json",
        }

        try:
            with self.client.stream(
                "POST",
                f"{self.profile.base_url}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    body = response.read().decode("utf-8", errors="replace")
                    raise ProviderError(
                        self._redact(
                            f"OpenAI 请求失败：HTTP {response.status_code}，{body}"
                        )
                    )

                for event in iter_sse_events(response.iter_lines()):
                    if event.data == "[DONE]":
                        break
                    yield from self._parse_event_data(event.data)
        except httpx.HTTPError as exc:
            raise ProviderError(self._redact(f"OpenAI 请求失败：{exc}")) from exc

    def _parse_event_data(self, data: str) -> Iterator[StreamChunk]:
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as exc:
            raise StreamProtocolError(
                self._redact(f"OpenAI 流式响应不是有效 JSON：{exc}")
            ) from exc

        error = chunk.get("error")
        if isinstance(error, dict):
            message = error.get("message") or str(error)
            raise ProviderError(self._redact(f"OpenAI 返回错误：{message}"))

        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return

        delta = first_choice.get("delta")
        if not isinstance(delta, dict):
            return

        content = delta.get("content")
        if isinstance(content, str) and content:
            yield StreamChunk(text=content)

    def _redact(self, text: str) -> str:
        return redact_secret(text, self.profile.api_key)
