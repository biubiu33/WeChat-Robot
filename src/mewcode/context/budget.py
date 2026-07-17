"""无需 tokenizer 的请求 Token 近似估算。"""

from __future__ import annotations

import math


DEFAULT_CONTEXT_WINDOW = 1_000_000
AUTO_RESERVE = 13_000
MANUAL_RESERVE = 3_000
CHARS_PER_TOKEN = 4


class TokenEstimator:
    def __init__(self) -> None:
        self._usage_tokens: int | None = None
        self._usage_chars = 0

    def record_usage(self, input_tokens: int, request_chars: int) -> None:
        if input_tokens >= 0 and request_chars >= 0:
            self._usage_tokens = input_tokens
            self._usage_chars = request_chars

    def estimate(self, request_chars: int) -> int:
        approximate = math.ceil(max(0, request_chars) / CHARS_PER_TOKEN)
        if self._usage_tokens is None:
            return approximate
        return max(
            0,
            self._usage_tokens
            + math.ceil((request_chars - self._usage_chars) / CHARS_PER_TOKEN),
        )

    def exceeds(
        self, request_chars: int, context_window: int, *, manual: bool = False
    ) -> bool:
        reserve = MANUAL_RESERVE if manual else AUTO_RESERVE
        return self.estimate(request_chars) > context_window - reserve
