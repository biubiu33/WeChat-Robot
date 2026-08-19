from __future__ import annotations

import threading

import pytest

from mewcode.wechat.models import ConversationRow, VisibleMessage
from mewcode.wechat.uia_client import (
    INPUT_CLASS,
    INPUT_ID,
    SEARCH_EDIT_CLASS,
    SEARCH_ITEM_PREFIX,
    SEARCH_RESULT_CLASS,
    WechatUiaClient,
    WechatUiaError,
)
from mewcode.wechat.uia_driver import WechatUiaDriver


class FakeHook:
    def start(self) -> bool:
        return True

    def close(self) -> None:
        pass

    def wait(self, timeout: float) -> bool:
        return True


class FakeClient:
    def __init__(self) -> None:
        self.rows = [ConversationRow("row-a", "好友A", signature="old")]
        self.messages: dict[str, list[VisibleMessage]] = {"好友A": []}
        self.current = ""
        self.private = True
        self.sent: list[tuple[str, str]] = []

    def visible_private_conversations(self) -> list[ConversationRow]:
        return list(self.rows)

    def focus_conversation(self, row: ConversationRow) -> None:
        self.current = row.name

    def current_conversation_is_private(self) -> bool:
        return self.private

    def visible_text_messages(self, row: ConversationRow) -> list[VisibleMessage]:
        return list(self.messages.get(row.name, []))

    def validate_target(self, name: str) -> bool:
        return self.current == name and self.private

    def send_text(self, row: ConversationRow, text: str) -> None:
        self.sent.append((row.name, text))


def message(key: str, text: str) -> VisibleMessage:
    return VisibleMessage(key, "row-a", text, True, sender_name="好友A")


def test_baseline_ignores_history_and_emits_changed_unread_text() -> None:
    client = FakeClient()
    driver = WechatUiaDriver(client, FakeHook(), reconcile_seconds=0.2)
    driver.establish_baseline()

    assert driver.wait_for_events(threading.Event()) == []

    client.rows = [ConversationRow("row-a", "好友A", signature="new", unread_count=1)]
    client.messages["好友A"] = [message("m-old", "旧消息"), message("m-new", "你好")]
    events = driver.wait_for_events(threading.Event())

    assert [event.text for event in events] == ["你好"]
    assert events[0].incoming and events[0].private


def test_group_or_duplicate_name_is_safely_ignored() -> None:
    client = FakeClient()
    driver = WechatUiaDriver(client, FakeHook())
    driver.establish_baseline()
    client.rows = [
        ConversationRow("one", "同名", signature="a", unread_count=1),
        ConversationRow("two", "同名", signature="b", unread_count=1),
    ]
    client.messages["同名"] = [message("m", "消息")]

    assert driver.wait_for_events(threading.Event()) == []

    client.rows = [ConversationRow("group", "群", signature="new", unread_count=1)]
    client.messages["群"] = [message("g", "群消息")]
    client.private = False
    assert driver.wait_for_events(threading.Event()) == []


def test_non_allowlisted_row_is_not_opened_or_read() -> None:
    client = FakeClient()
    driver = WechatUiaDriver(
        client,
        FakeHook(),
        allowed_contacts={"好友A"},
    )
    driver.establish_baseline()
    client.rows = [ConversationRow("row-x", "陌生人", signature="new", unread_count=1)]
    client.messages["陌生人"] = [message("x", "不应读取")]

    assert driver.wait_for_events(threading.Event()) == []
    assert client.current == ""


def test_same_text_with_different_message_identity_is_not_deduplicated() -> None:
    row = ConversationRow("row-a", "好友A")
    first = WechatUiaDriver._event(
        row, message("one", "相同"), [message("one", "相同")], 0
    )
    second = WechatUiaDriver._event(
        row, message("two", "相同"), [message("two", "相同")], 0
    )

    assert first.fingerprint != second.fingerprint


def test_target_validation_and_send_are_delegated_under_original_name() -> None:
    client = FakeClient()
    driver = WechatUiaDriver(client, FakeHook())
    client.current = "好友A"
    event = WechatUiaDriver._event(
        client.rows[0], message("m", "你好"), [message("m", "你好")], 0
    )

    assert driver.validate_target(event) is True
    driver.send_text(event, "回复")
    assert client.sent == [("好友A", "回复")]


def test_keyboard_search_switches_conversation_without_click() -> None:
    class Value:
        Value = ""

        def SetValue(self, text: str) -> None:
            self.Value = text

    value = Value()

    class Search:
        ClassName = SEARCH_EDIT_CLASS

        def GetValuePattern(self) -> Value:
            return value

    class Result:
        ClassName = SEARCH_RESULT_CLASS
        Name = "好友A"

    class Window:
        active = False

        def SetActive(self) -> None:
            self.active = True

    client = object.__new__(WechatUiaClient)
    client.current = "好友B"

    class Auto:
        focused = None
        keys: list[str] = []

        def SendKeys(self, text: str, **_: object) -> None:
            self.keys.append(text)
            if text == "{Ctrl}f":
                self.focused = Search()
            elif text == "{Ctrl}a":
                value.Value = ""
            elif text == "{Enter}":
                client.current = "好友A"
            else:
                value.Value += text

        def GetFocusedControl(self) -> object:
            return self.focused

    window = Window()
    client._auto = Auto()
    client._activate_window = lambda active_window, **_: active_window.SetActive()
    client._main_window = lambda: window
    client.current_conversation_name = lambda: client.current
    client._find_all = lambda root, automation_id=None: (
        [Result()] if automation_id == f"{SEARCH_ITEM_PREFIX}好友A" else []
    )

    client._open_conversation_with_search(window, "好友A", timeout_seconds=0.1)

    assert window.active is True
    assert client.current == "好友A"
    assert client._auto.keys == ["{Ctrl}f", "{Ctrl}a", "好友A", "{Enter}"]


def test_keyboard_send_requires_input_focus_and_clear() -> None:
    class Value:
        Value = "回复"

        def SetValue(self, text: str) -> None:
            self.Value = text

    value = Value()
    client = object.__new__(WechatUiaClient)

    class Input:
        AutomationId = INPUT_ID
        ClassName = INPUT_CLASS

        def SetFocus(self) -> None:
            client._auto.focused = self

    class Auto:
        focused = None
        keys: list[str] = []

        def GetFocusedControl(self) -> object:
            return self.focused

        def SendKeys(self, text: str, **_: object) -> None:
            self.keys.append(text)
            value.Value = ""

    client._auto = Auto()
    client.validate_target = lambda name: name == "好友A"
    client._send_with_enter(Input(), value, "好友A", "回复")

    assert client._auto.keys == ["{Enter}"]
    assert value.Value == ""


def test_keyboard_send_false_success_clears_owned_input_and_fails() -> None:
    class Value:
        Value = "回复"

        def SetValue(self, text: str) -> None:
            self.Value = text

    value = Value()
    client = object.__new__(WechatUiaClient)

    class Input:
        AutomationId = INPUT_ID
        ClassName = INPUT_CLASS

        def SetFocus(self) -> None:
            client._auto.focused = self

    class Auto:
        focused = None

        def GetFocusedControl(self) -> object:
            return self.focused

        def SendKeys(self, text: str, **_: object) -> None:
            value.Value += "\n"

    client._auto = Auto()
    client.validate_target = lambda name: name == "好友A"
    with pytest.raises(WechatUiaError, match="消息可能未发送"):
        client._send_with_enter(Input(), value, "好友A", "回复", timeout_seconds=0)

    assert value.Value == ""
