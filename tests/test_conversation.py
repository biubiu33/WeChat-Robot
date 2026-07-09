from __future__ import annotations

from mewcode.conversation import Conversation


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
