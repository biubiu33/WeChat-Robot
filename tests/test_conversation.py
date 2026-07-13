from __future__ import annotations

from mewcode.conversation import Conversation
from mewcode.llm import ToolCall, ToolResult


def test_conversation_keeps_order_and_returns_copy() -> None:
    conv = Conversation()
    conv.add_user("你好")
    conv.add_assistant("你好，我是 MewCode")

    messages = conv.messages()
    assert [(m.role, m.content) for m in messages] == [
        ("user", "你好"),
        ("assistant", "你好，我是 MewCode"),
    ]

    messages.append(messages[-1])
    assert len(conv.messages()) == 2


def test_conversation_keeps_tool_round_in_order() -> None:
    conv = Conversation()
    calls = [
        ToolCall(id="call-1", name="read_file", input='{"path":"a.py"}'),
        ToolCall(id="call-2", name="grep", input='{"pattern":"TODO"}'),
    ]
    results = [
        ToolResult(tool_call_id="call-1", content="1\tprint('ok')"),
        ToolResult(tool_call_id="call-2", content="没有匹配", is_error=False),
    ]

    conv.add_user("检查代码")
    conv.add_assistant_with_tool_calls("我先检查。", calls)
    conv.add_tool_results(results)
    conv.add_assistant("检查完成。")

    calls.clear()
    results.clear()
    messages = conv.messages()
    assert [message.role for message in messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert len(messages[1].tool_calls) == 2
    assert len(messages[2].tool_results) == 2
    assert len(conv) == 4
