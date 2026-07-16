from __future__ import annotations

import asyncio
from types import SimpleNamespace

from mewcode.llm import (
    Message,
    Request,
    System,
    ToolCall,
    ToolDefinition,
    ToolResult,
    Usage,
    redact_secret,
)
from mewcode.llm.anthropic_provider import (
    AnthropicProvider,
    _append_reminder,
    _extract_text_delta as anthropic_text,
    _has_tool_history,
    to_anthropic_messages,
    to_anthropic_system,
    to_anthropic_tools,
)
from mewcode.llm.openai_provider import (
    OpenAIProvider,
    _accumulate_tool_call_deltas,
    _build_tool_calls,
    _extract_text_delta as openai_text,
    _extract_usage as openai_usage,
    to_openai_messages,
    to_openai_tools,
)


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


def test_text_delta_extractors_and_redaction() -> None:
    anthropic_event = SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text="你好"),
    )
    openai_event = SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content="你好"))]
    )

    assert anthropic_text(anthropic_event) == "你好"
    assert openai_text(openai_event) == "你好"
    assert redact_secret("bad sk-secret key", "sk-secret") == "bad *** key"


def test_openai_messages_use_two_system_blocks_and_keep_reminder_out_of_history() -> (
    None
):
    call = ToolCall("call-1", "read_file", '{"path":"a.py"}')
    request = Request(
        messages=[
            Message(role="user", content="读取"),
            Message(role="assistant", content="我来读取", tool_calls=[call]),
            Message(
                role="tool",
                tool_results=[ToolResult("call-1", "1\tprint('ok')")],
            ),
        ],
        tools=[_definition()],
        system=System(stable="稳定提示", environment="环境信息"),
        reminder="<system-reminder>计划模式</system-reminder>",
    )

    converted = to_openai_messages(request)

    assert to_openai_tools(request.tools)[0]["function"]["name"] == "read_file"
    assert converted[:2] == [
        {"role": "system", "content": "稳定提示"},
        {"role": "system", "content": "环境信息"},
    ]
    assert converted[3]["tool_calls"][0]["id"] == "call-1"
    assert converted[4]["tool_call_id"] == "call-1"
    assert converted[-1] == {
        "role": "user",
        "content": "<system-reminder>计划模式</system-reminder>",
    }
    assert all("system-reminder" not in message.content for message in request.messages)


def test_anthropic_reminder_is_merged_into_last_user_message() -> None:
    messages = to_anthropic_messages([Message(role="user", content="请规划")])

    _append_reminder(messages, "<system-reminder>只读</system-reminder>")

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"][0]["text"] == "请规划"
    assert messages[0]["content"][1]["text"].endswith("只读</system-reminder>")


def test_tool_history_conversion_and_tool_call_fragment_collection() -> None:
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
    converted = to_anthropic_messages(messages)
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
                            )
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
                                index=0,
                                id=None,
                                function=SimpleNamespace(
                                    name="file", arguments='a.py"}'
                                ),
                            )
                        ]
                    )
                )
            ]
        ),
    ]

    for chunk in chunks:
        _accumulate_tool_call_deltas(chunk, buffers)

    assert to_anthropic_tools([_definition()])[0]["name"] == "read_file"
    assert converted[1]["content"][0]["type"] == "tool_use"
    assert converted[2]["content"][1]["is_error"] is True
    assert _has_tool_history(messages)
    assert _build_tool_calls(buffers) == [
        ToolCall("call-a", "read_file", '{"path":"a.py"}')
    ]


def test_openai_usage_reads_cache_tokens_and_missing_fields_are_safe() -> None:
    chunk = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=7,
            prompt_tokens_details=SimpleNamespace(cached_tokens=9),
        )
    )

    assert openai_usage(chunk) == Usage(12, 7, cache_read=9)
    assert openai_usage(SimpleNamespace(usage=None)) is None


def test_openai_provider_serializes_request_and_streams_usage() -> None:
    captured: dict[str, object] = {}
    chunks = [
        SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="完成"))]
        ),
        SimpleNamespace(
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=7,
                prompt_tokens_details=SimpleNamespace(cached_tokens=9),
            ),
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
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    provider._api_key = "secret"
    provider._model = "test-model"
    request = Request(
        messages=[Message(role="user", content="读取")],
        tools=[_definition()],
        system=System(stable="稳定提示", environment="环境信息"),
    )

    async def collect():
        return [event async for event in provider.stream(request)]

    events = asyncio.run(collect())

    assert captured["messages"][:2] == [
        {"role": "system", "content": "稳定提示"},
        {"role": "system", "content": "环境信息"},
    ]
    assert captured["tools"] == to_openai_tools([_definition()])
    assert Usage(12, 7, cache_read=9) in [event.usage for event in events]
    assert events[-1].done


def test_anthropic_provider_uses_cache_block_and_reports_cache_usage() -> None:
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
            return SimpleNamespace(
                content=[],
                usage=SimpleNamespace(
                    input_tokens=11,
                    output_tokens=6,
                    cache_creation_input_tokens=20,
                    cache_read_input_tokens=30,
                ),
            )

    class FakeMessages:
        def stream(self, **params):
            captured.append(params)
            return FakeStream()

    provider = object.__new__(AnthropicProvider)
    provider._client = SimpleNamespace(messages=FakeMessages())
    provider._api_key = "secret"
    provider._model = "test-model"
    provider._thinking = True
    request = Request(
        messages=[Message(role="user", content="读取")],
        tools=[_definition()],
        system=System(stable="稳定提示", environment="环境信息"),
        reminder="<system-reminder>计划模式</system-reminder>",
    )

    async def collect():
        return [event async for event in provider.stream(request)]

    events = asyncio.run(collect())

    assert captured[0]["system"] == to_anthropic_system(request)
    assert captured[0]["tools"] == to_anthropic_tools([_definition()])
    assert captured[0]["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert captured[0]["messages"][-1]["content"][-1]["text"].endswith(
        "计划模式</system-reminder>"
    )
    assert Usage(11, 6, cache_write=20, cache_read=30) in [
        event.usage for event in events
    ]
