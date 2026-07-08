from __future__ import annotations

import json
from collections.abc import Iterator, Sequence

import httpx

from mewcode.errors import ProviderError, StreamProtocolError
from mewcode.http import create_http_client
from mewcode.models import ChatMessage, ProviderProfile, StreamChunk
from mewcode.providers.base import redact_secret
from mewcode.sse import SSEEvent, iter_sse_events


ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    def __init__(
        self, profile: ProviderProfile, client: httpx.Client | None = None
    ) -> None:
        self.profile = profile
        self.client = client or create_http_client()

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[StreamChunk]:
        payload: dict[str, object] = {
            "model": self.profile.model,
            "max_tokens": 4096,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": True,
        }
        if self.profile.thinking:
            payload["thinking"] = {"type": "adaptive", "display": "omitted"}

        headers = {
            "x-api-key": self.profile.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        try:
            with self.client.stream(
                "POST",
                f"{self.profile.base_url}/messages",
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    body = response.read().decode("utf-8", errors="replace")
                    raise ProviderError(
                        self._redact(
                            f"Claude 请求失败：HTTP {response.status_code}，{body}"
                        )
                    )

                for event in iter_sse_events(response.iter_lines()):
                    yield from self._parse_event(event)
        except httpx.HTTPError as exc:
            raise ProviderError(self._redact(f"Claude 请求失败：{exc}")) from exc

    def _parse_event(self, event: SSEEvent) -> Iterator[StreamChunk]:
        try:
            payload = json.loads(event.data)
        except json.JSONDecodeError as exc:
            raise StreamProtocolError(
                self._redact(f"Claude 流式响应不是有效 JSON：{exc}")
            ) from exc

        event_type = event.event or payload.get("type")
        if event_type == "error":
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or str(error)
            else:
                message = str(error or payload)
            raise ProviderError(self._redact(f"Claude 返回错误：{message}"))

        if event_type != "content_block_delta":
            return

        delta = payload.get("delta")
        if not isinstance(delta, dict):
            return

        if delta.get("type") != "text_delta":
            return

        text = delta.get("text")
        if isinstance(text, str) and text:
            yield StreamChunk(text=text)

    def _redact(self, text: str) -> str:
        return redact_secret(text, self.profile.api_key)
