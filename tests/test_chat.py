from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from mewcode.chat import run_chat
from mewcode.errors import ProviderError
from mewcode.io import ConsoleIO
from mewcode.models import ChatMessage, StreamChunk


@dataclass
class FakeIO:
    inputs: list[str]
    outputs: list[str] = field(default_factory=list)
    flush_count: int = 0

    def make_console(self) -> ConsoleIO:
        return ConsoleIO(input=self.read, write=self.outputs.append, flush=self.flush)

    def read(self, prompt: str) -> str:
        self.outputs.append(prompt)
        if not self.inputs:
            raise EOFError
        return self.inputs.pop(0)

    def flush(self) -> None:
        self.flush_count += 1

    @property
    def text(self) -> str:
        return "".join(self.outputs)


class FakeProvider:
    def __init__(self, replies: list[list[str]]) -> None:
        self.replies = replies
        self.calls: list[list[ChatMessage]] = []

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[StreamChunk]:
        self.calls.append(list(messages))
        reply = self.replies.pop(0) if self.replies else ["默认回复"]
        for text in reply:
            yield StreamChunk(text=text)


class FailingThenWorkingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[StreamChunk]:
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("网络断开")
        yield StreamChunk(text="恢复")


def test_chat_sends_full_history_each_turn() -> None:
    io = FakeIO(inputs=["第一轮", "第二轮", "退出"])
    provider = FakeProvider([["回复一"], ["回复二"]])

    result = run_chat(provider, "openai", io.make_console())

    assert result == 0
    assert provider.calls[0] == [ChatMessage(role="user", content="第一轮")]
    assert provider.calls[1] == [
        ChatMessage(role="user", content="第一轮"),
        ChatMessage(role="assistant", content="回复一"),
        ChatMessage(role="user", content="第二轮"),
    ]


def test_stream_chunks_are_flushed() -> None:
    io = FakeIO(inputs=["你好", "退出"])
    provider = FakeProvider([["你", "好"]])

    run_chat(provider, "openai", io.make_console())

    assert "MewCode> 你好" in io.text
    assert io.flush_count >= 4


def test_successful_reply_is_saved_to_history() -> None:
    io = FakeIO(inputs=["第一轮", "第二轮", "退出"])
    provider = FakeProvider([["甲", "乙"], ["丙"]])

    run_chat(provider, "openai", io.make_console())

    assert ChatMessage(role="assistant", content="甲乙") in provider.calls[1]


def test_provider_error_allows_continuing() -> None:
    io = FakeIO(inputs=["失败", "再试", "退出"])
    provider = FailingThenWorkingProvider()

    result = run_chat(provider, "openai", io.make_console())

    assert result == 0
    assert "请求失败：网络断开" in io.text
    assert "MewCode> 恢复" in io.text
    assert provider.calls == 2


def test_empty_input_is_ignored() -> None:
    io = FakeIO(inputs=["", "退出"])
    provider = FakeProvider([["不应调用"]])

    run_chat(provider, "openai", io.make_console())

    assert provider.calls == []


def test_exit_commands_stop_chat() -> None:
    for command in ["/exit", "/quit", "退出", "再见"]:
        io = FakeIO(inputs=[command])
        provider = FakeProvider([["不应调用"]])

        result = run_chat(provider, "openai", io.make_console())

        assert result == 0
        assert provider.calls == []
        assert "已退出 MewCode" in io.text


def test_eof_stops_chat() -> None:
    io = FakeIO(inputs=[])
    provider = FakeProvider([["不应调用"]])

    result = run_chat(provider, "openai", io.make_console())

    assert result == 0
    assert provider.calls == []
