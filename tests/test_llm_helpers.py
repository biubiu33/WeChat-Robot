from __future__ import annotations

from types import SimpleNamespace

from mewcode.llm import redact_secret
from mewcode.llm.anthropic_provider import _extract_text_delta as anthropic_text
from mewcode.llm.openai_provider import _extract_text_delta as openai_text


def test_anthropic_extracts_only_text_delta() -> None:
    event = SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text="你好"),
    )
    thinking = SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="thinking_delta", thinking="secret"),
    )

    assert anthropic_text(event) == "你好"
    assert anthropic_text(thinking) == ""


def test_openai_extracts_delta_content() -> None:
    chunk = SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content="你好"))]
    )
    empty = SimpleNamespace(choices=[])

    assert openai_text(chunk) == "你好"
    assert openai_text(empty) == ""


def test_redact_secret_removes_api_key() -> None:
    assert redact_secret("bad sk-secret key", "sk-secret") == "bad *** key"
