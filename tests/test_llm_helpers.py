from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mewcode.llm import Message, ToolCall, ToolDefinition, ToolResult, redact_secret
from mewcode.llm.anthropic_provider import (
    AnthropicProvider,
    _extract_text_delta as anthropic_text,
    _extract_tool_calls,
    _has_tool_history,
    to_anthropic_messages,
    to_anthropic_tools,
)
from mewcode.llm.openai_provider import (
    OpenAIProvider,
    _accumulate_tool_call_deltas,
    _build_tool_calls,
    _extract_text_delta as openai_text,
    to_openai_messages,
    to_openai_tools,
)


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


def _definition() -> ToolDefinition:
    return ToolDefinition(
        name="read_file",
        description="读取文件",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )


def test_openai_converts_tools_and_tool_history() -> None:
    call = ToolCall("call-1", "read_file", '{"path":"a.py"}')
    messages = [
        Message(role="user", content="读取"),
        Message(role="assistant", content="我来读取", tool_calls=[call]),
        Message(
            role="tool",
            tool_results=[ToolResult("call-1", "1\tprint('ok')")],
        ),
    ]

    tools = to_openai_tools([_definition()])
    converted = to_openai_messages(messages)

    assert tools[0]["function"]["parameters"]["required"] == ["path"]
    assert converted[0]["role"] == "system"
    assert converted[2]["tool_calls"][0]["id"] == "call-1"
    assert converted[3] == {
        "role": "tool",
        "tool_call_id": "call-1",
        "content": "1\tprint('ok')",
    }


def test_openai_accumulates_interleaved_tool_call_fragments() -> None:
    buffers: dict[int, dict[str, str]] = {}
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call-a",
                                function=SimpleNamespace(
                                    name="read_", arguments='{"path":"'
                                ),
                            ),
                            SimpleNamespace(
                                index=1,
                                id="call-b",
                                function=SimpleNamespace(
                                    name="grep", arguments='{"pattern":"'
                                ),
                            ),
                        ]
                    )
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                index=1,
                                id=None,
                                function=SimpleNamespace(name=None, arguments='TODO"}'),
                            ),
                            SimpleNamespace(
                                index=0,
                                id=None,
                                function=SimpleNamespace(
                                    name="file", arguments='a.py"}'
                                ),
                            ),
                        ]
                    )
                )
            ]
        ),
    ]

    for chunk in chunks:
        _accumulate_tool_call_deltas(chunk, buffers)

    assert _build_tool_calls(buffers) == [
        ToolCall("call-a", "read_file", '{"path":"a.py"}'),
        ToolCall("call-b", "grep", '{"pattern":"TODO"}'),
    ]


def test_anthropic_converts_tools_and_tool_history() -> None:
    calls = [
        ToolCall("call-1", "read_file", '{"path":"a.py"}'),
        ToolCall("call-2", "grep", '{"pattern":"TODO"}'),
    ]
    messages = [
        Message(role="user", content="检查"),
        Message(role="assistant", tool_calls=calls),
        Message(
            role="tool",
            tool_results=[
                ToolResult("call-1", "文件内容"),
                ToolResult("call-2", "失败", is_error=True),
            ],
        ),
    ]

    tools = to_anthropic_tools([_definition()])
    converted = to_anthropic_messages(messages)

    assert tools[0]["input_schema"]["required"] == ["path"]
    assert converted[1]["content"][0]["type"] == "tool_use"
    assert converted[2]["role"] == "user"
    assert converted[2]["content"][1]["is_error"] is True
    assert _has_tool_history(messages)


def test_anthropic_extracts_multiple_final_tool_calls() -> None:
    final_message = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="先检查"),
            SimpleNamespace(
                type="tool_use", id="1", name="read_file", input={"path": "a.py"}
            ),
            SimpleNamespace(
                type="tool_use", id="2", name="grep", input={"pattern": "TODO"}
            ),
        ]
    )

    calls = _extract_tool_calls(final_message)

    assert [call.name for call in calls] == ["read_file", "grep"]
    assert calls[0].input == '{"path": "a.py"}'


def test_openai_stream_injects_tools_and_emits_complete_call() -> None:
    captured: dict[str, object] = {}
    chunks = [
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call-1",
                                function=SimpleNamespace(
                                    name="read_file", arguments='{"path":"'
                                ),
                            )
                        ],
                    )
                )
            ]
        ),
        SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id=None,
                                function=SimpleNamespace(name=None, arguments='a.py"}'),
                            )
                        ],
                    )
                )
            ]
        ),
    ]

    class FakeStream:
        def __aiter__(self):
            async def iterate():
                for chunk in chunks:
                    yield chunk

            return iterate()

    class FakeCompletions:
        async def create(self, **params):
            captured.update(params)
            return FakeStream()

    provider = object.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(  # type: ignore[attr-defined]
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    provider._api_key = "secret"  # type: ignore[attr-defined]
    provider._model = "test-model"  # type: ignore[attr-defined]

    async def collect_events():
        return [
            event
            async for event in provider.stream(
                [Message(role="user", content="读取")], [_definition()]
            )
        ]

    events = asyncio.run(collect_events())

    assert captured["tools"] == to_openai_tools([_definition()])
    assert captured["tool_choice"] == "auto"
    assert events[-2].tool_calls == [
        ToolCall("call-1", "read_file", '{"path":"a.py"}')
    ]
    assert events[-1].done


def test_anthropic_stream_injects_tools_and_disables_thinking_for_followup() -> None:
    captured: list[dict[str, object]] = []

    class FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def __aiter__(self):
            async def iterate():
                yield SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="text_delta", text="完成"),
                )

            return iterate()

        async def get_final_message(self):
            return SimpleNamespace(content=[])

    class FakeMessages:
        def stream(self, **params):
            captured.append(params)
            return FakeStream()

    provider = object.__new__(AnthropicProvider)
    provider._client = SimpleNamespace(messages=FakeMessages())  # type: ignore[attr-defined]
    provider._api_key = "secret"  # type: ignore[attr-defined]
    provider._model = "test-model"  # type: ignore[attr-defined]
    provider._thinking = True  # type: ignore[attr-defined]
    call = ToolCall("call-1", "read_file", '{"path":"a.py"}')

    async def run_requests():
        first = [
            event
            async for event in provider.stream(
                [Message(role="user", content="读取")], [_definition()]
            )
        ]
        followup = [
            event
            async for event in provider.stream(
                [
                    Message(role="user", content="读取"),
                    Message(role="assistant", tool_calls=[call]),
                    Message(
                        role="tool",
                        tool_results=[ToolResult("call-1", "文件内容")],
                    ),
                ],
                [_definition()],
            )
        ]
        return first, followup

    first, followup = asyncio.run(run_requests())

    assert captured[0]["tools"] == to_anthropic_tools([_definition()])
    assert captured[0]["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert "thinking" not in captured[1]
    assert captured[1]["messages"][-1]["content"][0]["type"] == "tool_result"
    assert first[-1].done and followup[-1].done
