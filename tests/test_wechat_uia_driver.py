from __future__ import annotations

import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from mewcode.wechat.models import (
    ConversationRow,
    MessageReference,
    QueuedBatch,
    ResolvedReference,
    VisibleMessage,
)
from mewcode.wechat.uia_client import (
    INPUT_CLASS,
    INPUT_ID,
    MAIN_WINDOW_CLASS,
    SEARCH_EDIT_CLASS,
    SEARCH_RESULT_CLASS,
    SUPPORTED_WECHAT_VERSIONS,
    WechatUiaClient,
    WechatUiaError,
    WechatReferenceTargetError,
)
from mewcode.wechat.uia_driver import WechatUiaDriver, strip_self_mention


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

    def current_conversation_name(self) -> str:
        return self.current

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


def test_private_scan_only_emits_unread_delta_after_startup_baseline() -> None:
    client = FakeClient()
    client.rows = [
        ConversationRow("row-a", "好友A", signature="old", unread_count=1)
    ]
    driver = WechatUiaDriver(client, FakeHook(), reconcile_seconds=0.2)
    driver.establish_baseline()
    client.rows = [
        ConversationRow("row-a", "好友A", signature="new", unread_count=2)
    ]
    client.messages["好友A"] = [
        message("startup", "启动前旧图片"),
        message("new", "启动后新消息"),
    ]

    events = driver.wait_for_events(threading.Event())

    assert [item.text for item in events] == ["启动后新消息"]


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


def test_image_event_keeps_identity_and_batch_text_excludes_placeholder() -> None:
    row = ConversationRow("row-a", "好友A")
    visible = VisibleMessage(
        "image-1",
        "row-a",
        "[图片]",
        True,
        kind="image",
        sender_name="好友A",
        bounds=(1, 2, 30, 40),
    )
    event = WechatUiaDriver._event(row, visible, [visible], 0)
    text_event = WechatUiaDriver._event(
        row, message("text", "比较"), [message("text", "比较")], 0
    )
    batch = QueuedBatch("好友A", (event, text_event), 1, 0)

    assert event.message_key == "image-1"
    assert event.message_kind == "image"
    assert event.bounds == (1, 2, 30, 40)
    assert batch.text == "比较"
    assert batch.image_events == (event,)


def test_reference_model_and_batch_keep_one_layer() -> None:
    reference = MessageReference("Alice", "Bob 引用 Carol 的消息：原文", "text")
    visible = VisibleMessage(
        "quote-1",
        "row-a",
        "你怎么看",
        True,
        reference=reference,
    )
    event = WechatUiaDriver._event(
        ConversationRow("row-a", "好友A"), visible, [visible], 0
    )
    batch = QueuedBatch("好友A", (event,), 0, 0, immutable=True)

    assert event.reference == reference
    assert batch.reference_event == event
    assert batch.image_events == ()


def test_flattened_reference_label_separates_current_and_one_preview() -> None:
    parsed = WechatUiaClient._parse_reference_label(
        "测试引用引用 Alice 的消息 : Bob 引用 Carol 的消息 : 完整原文"
    )

    assert parsed == (
        "测试引用",
        MessageReference(
            "Alice",
            "Bob 引用 Carol 的消息 : 完整原文",
            "text",
        ),
    )


@pytest.mark.parametrize(
    ("preview", "kind", "unsupported"),
    [
        ("图片", "image", ""),
        ("Image", "image", ""),
        ("语音", "unsupported", "voice"),
        ("[视频]", "unsupported", "video"),
        ("【分享卡片】", "unsupported", "share_card"),
        ("[文件]", "unsupported", "file"),
        ("报告.pdf", "unsupported", "file"),
        ("普通文字", "text", ""),
    ],
)
def test_reference_label_classifies_supported_scope(
    preview: str, kind: str, unsupported: str
) -> None:
    parsed = WechatUiaClient._parse_reference_label(
        f"问题引用 Alice 的消息：{preview}"
    )

    assert parsed is not None
    assert parsed[1].kind == kind
    assert parsed[1].unsupported_type == unsupported


def test_same_question_with_different_references_has_distinct_fingerprint() -> None:
    row = ConversationRow("row-a", "好友A")
    left = VisibleMessage(
        "same-runtime",
        "row-a",
        "怎么看",
        True,
        reference=MessageReference("Alice", "甲", "text"),
    )
    right = VisibleMessage(
        "same-runtime",
        "row-a",
        "怎么看",
        True,
        reference=MessageReference("Bob", "乙", "text"),
    )

    assert WechatUiaDriver._event(row, left, [left], 0).fingerprint != (
        WechatUiaDriver._event(row, right, [right], 0).fingerprint
    )


def test_reference_control_requires_exact_snapshot_identity() -> None:
    reference = MessageReference("Alice", "原文", "text")

    def control(runtime: int, name: str):
        return SimpleNamespace(
            Name=name,
            GetRuntimeId=lambda: [runtime],
            BoundingRectangle=SimpleNamespace(
                left=0, top=0, right=100, bottom=100
            ),
        )

    wanted = control(1, "问题引用 Alice 的消息：原文")
    wrong_sender = control(2, "问题引用 Bob 的消息：原文")
    message_list = SimpleNamespace(GetChildren=lambda: [wanted, wrong_sender])
    client = object.__new__(WechatUiaClient)

    assert client._find_reference_control(
        message_list, "1", (0, 0, 100, 100), "问题", reference
    ) is wanted
    assert client._find_reference_control(
        message_list, "2", (0, 0, 100, 100), "问题", reference
    ) is wanted


def test_reference_activation_targets_quoted_lower_region() -> None:
    assert WechatUiaClient._reference_activation_point((100, 200, 500, 400)) == (
        200,
        352,
    )


def _reference_image_client(calls: list[str]) -> WechatUiaClient:
    client = object.__new__(WechatUiaClient)
    client._bounds = lambda control: control.bounds
    client.validate_target = lambda *_: True
    client._capture_viewer_from_point = (
        lambda point, window, target: calls.append("quote_viewer") or False
    )
    client._locate_referenced_original = (
        lambda control, reference: calls.append("locate") or None
    )
    client._restore_reference_target = lambda row: calls.append("restore")
    client._main_window = lambda: object()
    client._find_unique = lambda *_, **__: object()
    client._find_reference_control = lambda *args: args[0].quote
    client._capture_bounds = (
        lambda bounds, target: calls.append("thumbnail") or target.write_bytes(b"png") > 0
    )
    return client


def test_referenced_image_uses_direct_viewer_without_fallback(tmp_path: Path) -> None:
    calls: list[str] = []
    client = _reference_image_client(calls)
    client._capture_viewer_from_point = (
        lambda point, window, target: calls.append("quote_viewer") or target.write_bytes(b"png") > 0
    )
    control = SimpleNamespace(bounds=(0, 0, 100, 100))
    reference = MessageReference("Alice", "图片", "image")

    resolved = client._resolve_reference_image(
        ConversationRow("row", "好友A", private=True),
        control,
        "key",
        "问题",
        reference,
        tmp_path,
        object(),
    )

    assert resolved.capture is not None and resolved.degraded is False
    assert calls == ["quote_viewer"]


def test_referenced_image_falls_back_in_strict_order(tmp_path: Path) -> None:
    calls: list[str] = []
    client = _reference_image_client(calls)
    original = SimpleNamespace(
        bounds=(0, 0, 100, 100),
        ClassName="mmui::ChatImageItemView",
        Name="图片",
    )
    client._locate_referenced_original = (
        lambda control, reference: calls.append("locate") or original
    )
    client._capture_viewer = (
        lambda control, window, target: calls.append("original_viewer") or False
    )
    restored = SimpleNamespace(quote=SimpleNamespace(bounds=(0, 0, 100, 100)))
    client._find_unique = lambda *_, **__: restored
    control = SimpleNamespace(bounds=(0, 0, 100, 100))
    reference = MessageReference("Alice", "图片", "image")

    resolved = client._resolve_reference_image(
        ConversationRow("row", "好友A", private=True),
        control,
        "key",
        "问题",
        reference,
        tmp_path,
        object(),
    )

    assert resolved.capture is not None and resolved.degraded is True
    assert calls == [
        "quote_viewer",
        "locate",
        "original_viewer",
        "restore",
        "thumbnail",
    ]


def test_referenced_image_unsafe_viewer_stops_without_fallback(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    client = _reference_image_client(calls)
    client._capture_viewer_from_point = (
        lambda point, window, target: calls.append("quote_viewer") or None
    )

    with pytest.raises(WechatReferenceTargetError):
        client._resolve_reference_image(
            ConversationRow("row", "好友A", private=True),
            SimpleNamespace(bounds=(0, 0, 100, 100)),
            "key",
            "问题",
            MessageReference("Alice", "图片", "image"),
            tmp_path,
            object(),
        )

    assert calls == ["quote_viewer"]
    assert WechatUiaClient._reference_thumbnail_bounds((100, 200, 500, 400)) == (
        100,
        290,
        500,
        400,
    )


def test_driver_materializes_only_authorized_reference(tmp_path: Path) -> None:
    client = FakeClient()
    client.current = "好友A"
    reference = MessageReference("Alice", "原文", "text")
    resolved = ResolvedReference(reference, content="完整原文")
    calls = []
    client.resolve_reference = lambda *args: calls.append(args) or resolved
    driver = WechatUiaDriver(
        client,
        FakeHook(),
        allowed_contacts={"好友A"},
    )
    visible = VisibleMessage(
        "quote",
        "row-a",
        "问题",
        True,
        reference=reference,
    )
    event = WechatUiaDriver._event(client.rows[0], visible, [visible], 0)

    assert driver.materialize_reference(event, tmp_path) == resolved
    assert len(calls) == 1

    blocked = WechatUiaDriver(
        client,
        FakeHook(),
        allowed_contacts={"其他人"},
    )
    with pytest.raises(WechatReferenceTargetError):
        blocked.materialize_reference(event, tmp_path)
    assert len(calls) == 1


def test_group_reference_materialization_reuses_unstripped_current_text(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    client.current = "测试群聊"
    client.private = False
    client.validate_target = lambda name: client.current == name
    client._parse_reference_label = WechatUiaClient._parse_reference_label
    reference = MessageReference("张三", "图片", "image")
    resolved = ResolvedReference(reference, strategy="unavailable")
    calls = []
    client.resolve_reference = lambda *args: calls.append(args) or resolved
    driver = WechatUiaDriver(
        client,
        FakeHook(),
        allowed_contacts=set(),
        allowed_groups={"测试群聊"},
        self_names={"机器人"},
        group_sender_ocr=PassthroughGroupOcr(),
    )
    visible = VisibleMessage(
        "quote",
        "group",
        "@机器人 这张图是什么？",
        True,
        sender_name="李四",
        bounds=(1, 2, 100, 120),
        reference=reference,
        raw_text="@机器人 这张图是什么？引用 张三 的消息：图片",
    )
    event = WechatUiaDriver._event(
        ConversationRow("group", "测试群聊", private=False),
        visible,
        [visible],
        0,
        private=False,
        is_at=True,
        text="这张图是什么？",
    )

    assert driver.materialize_reference(event, tmp_path) == resolved
    assert calls[0][3] == "@机器人 这张图是什么？"


def test_image_reference_never_degrades_to_text_preview() -> None:
    reference = MessageReference("张三", "图片", "image")

    resolved = WechatUiaClient._reference_preview(reference)

    assert resolved.capture is None
    assert resolved.content == ""
    assert resolved.degraded is False
    assert resolved.strategy == "unavailable"


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


@pytest.mark.parametrize("supported_version", SUPPORTED_WECHAT_VERSIONS)
def test_main_window_accepts_supported_version_and_caches_handle(
    supported_version: str,
) -> None:
    window = SimpleNamespace(
        ClassName=MAIN_WINDOW_CLASS,
        NativeWindowHandle=42,
    )
    root = SimpleNamespace(GetChildren=lambda: [window])
    client = object.__new__(WechatUiaClient)
    client._auto = SimpleNamespace(GetRootControl=lambda: root)
    client._expected_versions = SUPPORTED_WECHAT_VERSIONS
    client._validated_hwnd = 0
    version_reads: list[object] = []
    client._wechat_version = lambda actual_window: (
        version_reads.append(actual_window) or supported_version
    )

    assert client._main_window() is window
    assert client._main_window() is window
    assert client._validated_hwnd == 42
    assert version_reads == [window]


def test_main_window_rejects_other_version() -> None:
    window = SimpleNamespace(
        ClassName=MAIN_WINDOW_CLASS,
        NativeWindowHandle=42,
    )
    root = SimpleNamespace(GetChildren=lambda: [window])
    client = object.__new__(WechatUiaClient)
    client._auto = SimpleNamespace(GetRootControl=lambda: root)
    client._expected_versions = SUPPORTED_WECHAT_VERSIONS
    client._validated_hwnd = 0
    client._wechat_version = lambda _: "4.1.12.55"

    with pytest.raises(
        WechatUiaError,
        match=r"仅支持微信 4\.0\.5\.15、4\.1\.9\.30，当前版本为 4\.1\.12\.55",
    ):
        client._main_window()


def test_main_window_reports_narrator_guidance_for_weixin_qt_shell() -> None:
    shell = SimpleNamespace(ClassName="Qt51514QWindowIcon", ProcessId=7)
    root = SimpleNamespace(GetChildren=lambda: [shell])
    client = object.__new__(WechatUiaClient)
    client._auto = SimpleNamespace(GetRootControl=lambda: root)
    client._expected_versions = SUPPORTED_WECHAT_VERSIONS
    client._validated_hwnd = 0
    client._wechat_process_path = lambda _: r"C:\Tencent\Weixin\Weixin.exe"

    with pytest.raises(
        WechatUiaError,
        match="请先启动 Windows 讲述人并重启微信",
    ):
        client._main_window()


def test_main_window_does_not_treat_other_qt_window_as_weixin() -> None:
    shell = SimpleNamespace(ClassName="Qt51514QWindowIcon", ProcessId=7)
    root = SimpleNamespace(GetChildren=lambda: [shell])
    client = object.__new__(WechatUiaClient)
    client._auto = SimpleNamespace(GetRootControl=lambda: root)
    client._expected_versions = SUPPORTED_WECHAT_VERSIONS
    client._validated_hwnd = 0
    client._wechat_process_path = lambda _: r"C:\Tools\OtherQt.exe"

    with pytest.raises(
        WechatUiaError,
        match="需要且只允许一个微信主窗口，当前找到 0 个",
    ):
        client._main_window()


def test_405_session_row_parses_exact_name_and_unread_count() -> None:
    row = SimpleNamespace(
        AutomationId="session_item",
        ClassName="mmui::ChatSessionCell",
        Name="biubiubiu仿生人 1条未读 你好 21:38",
        GetRuntimeId=lambda: [42, 7],
    )
    client = object.__new__(WechatUiaClient)
    client._thread_context = nullcontext
    client._main_window = object
    client._find_unique = lambda *_, **__: SimpleNamespace(GetChildren=lambda: [row])

    conversations = client.visible_private_conversations()

    assert len(conversations) == 1
    assert conversations[0].name == "biubiubiu仿生人"
    assert conversations[0].unread_count == 1


def test_visible_messages_includes_plain_image_but_text_wrapper_filters_it() -> None:
    text = SimpleNamespace(
        ClassName="mmui::ChatTextItemView",
        Name="你好",
        GetRuntimeId=lambda: [1],
    )
    image = SimpleNamespace(
        ClassName="mmui::ChatBubbleReferItemView",
        Name="图片",
        GetRuntimeId=lambda: [2],
    )
    quoted_image = SimpleNamespace(
        ClassName="mmui::ChatBubbleReferItemView",
        Name="请看这张图 引用 张三 的消息：图片",
        GetRuntimeId=lambda: [4],
    )
    file_item = SimpleNamespace(
        ClassName="mmui::ChatFileItemView",
        Name="x.zip",
        GetRuntimeId=lambda: [3],
    )
    message_list = SimpleNamespace(
        GetChildren=lambda: [text, image, quoted_image, file_item]
    )
    client = object.__new__(WechatUiaClient)
    client._thread_context = nullcontext
    client.current_conversation_name = lambda: "好友A"
    client.current_conversation_is_private = lambda: True
    client._main_window = object
    client._find_unique = lambda *_, **__: message_list
    client._bounds = lambda control: (0, 0, int(control.GetRuntimeId()[0]), 10)
    row = ConversationRow("row-a", "好友A", private=True)

    visible = client.visible_messages(row)

    assert [(item.key, item.kind, item.text) for item in visible] == [
        ("1", "text", "你好"),
        ("2", "image", "[图片]"),
        ("4", "text", "请看这张图"),
    ]
    assert [item.kind for item in client.visible_text_messages(row)] == [
        "text",
        "text",
    ]
    assert visible[-1].reference == MessageReference("张三", "图片", "image")


def test_capture_private_image_falls_back_to_bubble(tmp_path: Path) -> None:
    control = SimpleNamespace(
        ClassName="mmui::ChatBubbleReferItemView",
        Name="图片",
        GetRuntimeId=lambda: [2],
    )
    message_list = SimpleNamespace(GetChildren=lambda: [control])
    client = object.__new__(WechatUiaClient)
    client._thread_context = nullcontext
    client.focus_conversation = lambda row: None
    client.validate_target = lambda name, private=True: name == "好友A" and private
    client._main_window = object
    client._find_unique = lambda *_, **__: message_list
    client._bounds = lambda _: (1, 2, 20, 30)
    client._capture_viewer = lambda *_: False

    def capture_bounds(bounds, target):
        assert bounds == (1, 2, 20, 30)
        target.write_bytes(b"png")
        return True

    client._capture_bounds = capture_bounds

    result = client.capture_private_image(
        ConversationRow("row-a", "好友A", private=True),
        "2",
        (1, 2, 20, 30),
        tmp_path,
    )

    assert result is not None
    assert result.degraded is True
    assert result.path.read_bytes() == b"png"


def test_viewer_capture_closes_verified_window_and_restores_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from PIL import ImageGrab

    client = object.__new__(WechatUiaClient)
    client._click_preserving_cursor = lambda control: None
    client._opened_image_viewer = lambda main, before: 99
    client._close_image_viewer = lambda hwnd: hwnd == 99
    activated: list[object] = []
    client._activate_window = lambda window: activated.append(window)
    monkeypatch.setattr("mewcode.wechat.uia_client._visible_window_handles", lambda: {42})
    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(GetWindowRect=lambda hwnd: (0, 0, 20, 10)),
    )
    monkeypatch.setattr(
        ImageGrab,
        "grab",
        lambda **kwargs: __import__("PIL.Image", fromlist=["Image"]).new(
            "RGB", (20, 10), "red"
        ),
    )
    main = SimpleNamespace(NativeWindowHandle=42)
    target = tmp_path / "viewer.png"

    assert client._capture_viewer(object(), main, target) is True
    assert target.is_file()
    assert activated == [main]


def test_viewer_close_failure_is_unsafe_and_does_not_keep_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from PIL import ImageGrab

    client = object.__new__(WechatUiaClient)
    client._click_preserving_cursor = lambda control: None
    client._opened_image_viewer = lambda main, before: 99
    client._close_image_viewer = lambda hwnd: False
    client._activate_window = lambda window: None
    monkeypatch.setattr("mewcode.wechat.uia_client._visible_window_handles", lambda: set())
    monkeypatch.setitem(
        sys.modules,
        "win32gui",
        SimpleNamespace(GetWindowRect=lambda hwnd: (0, 0, 20, 10)),
    )
    monkeypatch.setattr(
        ImageGrab,
        "grab",
        lambda **kwargs: __import__("PIL.Image", fromlist=["Image"]).new(
            "RGB", (20, 10), "red"
        ),
    )
    target = tmp_path / "unsafe.png"

    assert (
        client._capture_viewer(
            object(), SimpleNamespace(NativeWindowHandle=42), target
        )
        is None
    )
    assert not target.exists()


def test_session_row_parses_group_mention_marker() -> None:
    row = SimpleNamespace(
        AutomationId="session_item_测试群聊",
        ClassName="mmui::ChatSessionCell",
        Name="测试群聊\n[2条] 张三: 你好 [有人@我]",
        GetRuntimeId=lambda: [42, 8],
    )
    client = object.__new__(WechatUiaClient)
    client._thread_context = nullcontext
    client._main_window = object
    client._find_unique = lambda *_, **__: SimpleNamespace(GetChildren=lambda: [row])

    [conversation] = client.visible_conversations()

    assert conversation.name == "测试群聊"
    assert conversation.mentions_self is True


class PassthroughGroupOcr:
    def preload(self) -> None:
        pass

    def enrich(self, messages, pane_bounds):
        del pane_bounds
        return list(messages)


def test_group_driver_emits_context_events_and_only_marks_exact_mentions() -> None:
    client = FakeClient()
    client.private = False
    client.rows = [ConversationRow("group", "测试群聊", signature="old")]
    client.messages["测试群聊"] = [
        VisibleMessage("old", "group", "旧消息", True, sender_name="张三")
    ]
    client.message_list_bounds = lambda: (0, 0, 800, 600)
    driver = WechatUiaDriver(
        client,
        FakeHook(),
        allowed_contacts=set(),
        allowed_groups={"测试群聊"},
        self_names={"biubiubiu仿生人"},
        group_sender_ocr=PassthroughGroupOcr(),
    )
    driver.establish_baseline()

    assert client.current == ""

    client.rows = [
        ConversationRow("group", "测试群聊", signature="new", unread_count=3)
    ]
    client.messages["测试群聊"] = [
        VisibleMessage(
            "old-runtime-changed", "group", "旧消息", True, sender_name="张三"
        ),
        VisibleMessage("normal", "group", "这是普通消息", True, sender_name="张三"),
        VisibleMessage(
            "at-1",
            "group",
            "@biubiubiu仿生人\u2005问题A",
            True,
            sender_name="张三",
        ),
        VisibleMessage(
            "at-2",
            "group",
            "@biubiubiu仿生人 问题B @李四",
            True,
            sender_name="王五",
        ),
    ]

    events = driver.wait_for_events(threading.Event())

    assert [(item.sender_name, item.is_at) for item in events] == [
        ("张三", False),
        ("张三", True),
        ("王五", True),
    ]
    assert events[1].text == "问题A"
    assert events[2].text == "问题B @李四"
    assert events[1].raw_text.startswith("@biubiubiu仿生人")


def test_group_driver_ignores_unknown_sender_even_with_exact_mention() -> None:
    client = FakeClient()
    client.private = False
    client.rows = [ConversationRow("group", "测试群聊", signature="old")]
    client.messages["测试群聊"] = []
    client.message_list_bounds = lambda: (0, 0, 800, 600)
    driver = WechatUiaDriver(
        client,
        FakeHook(),
        allowed_contacts=set(),
        allowed_groups={"测试群聊"},
        self_names={"biubiubiu仿生人"},
        group_sender_ocr=PassthroughGroupOcr(),
    )
    driver.establish_baseline()
    client.rows = [
        ConversationRow("group", "测试群聊", signature="new", unread_count=1)
    ]
    client.messages["测试群聊"] = [
        VisibleMessage(
            "unknown",
            "group",
            "@biubiubiu仿生人 你好",
            True,
            sender_name="",
        )
    ]

    assert driver.wait_for_events(threading.Event()) == []


def test_group_reference_trigger_uses_only_current_question_mention() -> None:
    client = FakeClient()
    client.private = False
    client.rows = [ConversationRow("group", "测试群聊", signature="old")]
    client.messages["测试群聊"] = []
    client.message_list_bounds = lambda: (0, 0, 800, 600)
    driver = WechatUiaDriver(
        client,
        FakeHook(),
        allowed_contacts=set(),
        allowed_groups={"测试群聊"},
        self_names={"biubiubiu仿生人"},
        group_sender_ocr=PassthroughGroupOcr(),
    )
    driver.establish_baseline()
    client.rows = [
        ConversationRow("group", "测试群聊", signature="new", unread_count=2)
    ]
    client.messages["测试群聊"] = [
        VisibleMessage(
            "preview-at",
            "group",
            "你怎么看",
            True,
            sender_name="张三",
            reference=MessageReference(
                "李四", "@biubiubiu仿生人 只在引用里", "text"
            ),
        ),
        VisibleMessage(
            "current-at",
            "group",
            "@biubiubiu仿生人 解释一下",
            True,
            sender_name="张三",
            reference=MessageReference("李四", "普通原文", "text"),
        ),
    ]

    events = driver.wait_for_events(threading.Event())

    assert [(item.text, item.is_at) for item in events] == [
        ("你怎么看", False),
        ("解释一下", True),
    ]


def test_already_open_group_detects_new_message_without_unread_count() -> None:
    client = FakeClient()
    client.current = "测试群聊"
    client.private = False
    client.rows = [ConversationRow("group", "测试群聊", signature="old")]
    client.messages["测试群聊"] = [
        VisibleMessage("old", "group", "旧消息", True, sender_name="张三")
    ]
    client.message_list_bounds = lambda: (0, 0, 800, 600)
    driver = WechatUiaDriver(
        client,
        FakeHook(),
        allowed_contacts=set(),
        allowed_groups={"测试群聊"},
        self_names={"机器人"},
        group_sender_ocr=PassthroughGroupOcr(),
    )
    driver.establish_baseline()

    client.rows = [ConversationRow("group", "测试群聊", signature="new")]
    client.messages["测试群聊"] = [
        VisibleMessage("old-changed", "group", "旧消息", True, sender_name="张三"),
        VisibleMessage("new", "group", "@机器人 你好", True, sender_name="张三"),
    ]

    events = driver.wait_for_events(threading.Event())

    assert [event.text for event in events] == ["你好"]


def test_group_runtime_id_can_be_reused_after_message_leaves_view() -> None:
    client = FakeClient()
    client.current = "测试群聊"
    client.private = False
    client.rows = [ConversationRow("group", "测试群聊", signature="baseline")]
    client.messages["测试群聊"] = []
    client.message_list_bounds = lambda: (0, 0, 800, 600)
    driver = WechatUiaDriver(
        client,
        FakeHook(),
        allowed_contacts=set(),
        allowed_groups={"测试群聊"},
        self_names={"机器人"},
        group_sender_ocr=PassthroughGroupOcr(),
    )
    driver.establish_baseline()

    client.rows = [ConversationRow("group", "测试群聊", signature="first")]
    client.messages["测试群聊"] = [
        VisibleMessage("reused", "group", "@机器人 第一轮", True, sender_name="张三")
    ]
    first = driver.wait_for_events(threading.Event())

    client.rows = [ConversationRow("group", "测试群聊", signature="reply")]
    client.messages["测试群聊"] = [
        VisibleMessage("outgoing", "group", "第一轮回复", False)
    ]
    assert driver.wait_for_events(threading.Event()) == []

    client.rows = [ConversationRow("group", "测试群聊", signature="second")]
    client.messages["测试群聊"] = [
        VisibleMessage("outgoing", "group", "第一轮回复", False),
        VisibleMessage("reused", "group", "@机器人 第二轮", True, sender_name="张三"),
    ]
    second = driver.wait_for_events(threading.Event())

    assert [event.text for event in first] == ["第一轮"]
    assert [event.text for event in second] == ["第二轮"]


def test_strip_self_mention_is_exact_and_preserves_other_mentions() -> None:
    cleaned, matched = strip_self_mention(
        "@biubiubiu仿生人\u2005帮我问一下 @张三",
        ["biubiubiu仿生人"],
    )
    not_cleaned, not_matched = strip_self_mention(
        "@biubiubiu仿生人助手 你好",
        ["biubiubiu仿生人"],
    )

    assert matched is True
    assert cleaned == "帮我问一下 @张三"
    assert not_matched is False
    assert not_cleaned == "@biubiubiu仿生人助手 你好"


def test_focus_conversation_uses_verified_search_for_generic_session_item() -> None:
    client = object.__new__(WechatUiaClient)
    client._thread_context = nullcontext
    client.current_conversation_name = lambda: "曾俊"
    window = object()
    client._main_window = lambda: window
    activated: list[object] = []
    client._activate_window = lambda actual_window, **_: activated.append(actual_window)
    opened: list[tuple[object, str]] = []
    client._open_conversation_with_search = lambda actual_window, name: opened.append(
        (actual_window, name)
    )

    client.focus_conversation(ConversationRow("42:7", "biubiubiu仿生人"))

    assert activated == [window]
    assert opened == [(window, "biubiubiu仿生人")]


def test_focus_conversation_activates_already_selected_group() -> None:
    client = object.__new__(WechatUiaClient)
    client._thread_context = nullcontext
    window = object()
    client._main_window = lambda: window
    client.current_conversation_name = lambda: "测试群聊"
    activated: list[object] = []
    client._activate_window = lambda actual_window, **_: activated.append(actual_window)

    client.focus_conversation(ConversationRow("group", "测试群聊", private=False))

    assert activated == [window]


def test_focus_group_clicks_unique_visible_session_row() -> None:
    client = object.__new__(WechatUiaClient)
    client._thread_context = nullcontext
    client.current = "好友A"
    window = object()

    class GroupRow:
        ClassName = "mmui::ChatSessionCell"
        Name = "测试群聊"

        def Click(self) -> None:
            client.current = self.Name

    group = GroupRow()
    session_list = SimpleNamespace(GetChildren=lambda: [group])
    client._main_window = lambda: window
    client._activate_window = lambda *_args, **_kwargs: None
    client.current_conversation_name = lambda: client.current
    client._find_unique = lambda *_args, **_kwargs: session_list
    client._conversation_name = lambda control, raw_name: raw_name
    clicked: list[object] = []

    def click(control: object) -> None:
        clicked.append(control)
        control.Click()

    client._click_preserving_cursor = click

    client.focus_conversation(ConversationRow("group", "测试群聊", private=False))

    assert client.current == "测试群聊"
    assert clicked == [group]


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
        AutomationId = ""

    class Window:
        active = False

        def SetActive(self) -> None:
            self.active = True

    client = object.__new__(WechatUiaClient)
    client.current = "好友B"

    class Auto:
        focused = None
        keys: ClassVar[list[str]] = []

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
    client._find_all = lambda root, automation_id=None: [Result()]

    client._open_conversation_with_search(window, "好友A", timeout_seconds=0.1)

    assert window.active is True
    assert client.current == "好友A"
    assert client._auto.keys == ["{Ctrl}f", "{Ctrl}a", "好友A", "{Enter}"]


def test_group_search_clicks_unique_result_instead_of_pressing_enter() -> None:
    value = SimpleNamespace(Value="")
    search = SimpleNamespace(
        ClassName=SEARCH_EDIT_CLASS,
        GetValuePattern=lambda: value,
    )
    client = object.__new__(WechatUiaClient)
    client.current = "好友A"
    keys: list[str] = []

    class Auto:
        focused = search

        def SendKeys(self, text: str, **_: object) -> None:
            keys.append(text)
            if text == "{Ctrl}a":
                value.Value = ""
            elif not text.startswith("{"):
                value.Value += text

        def GetFocusedControl(self) -> object:
            return self.focused

    class Result:
        ClassName = SEARCH_RESULT_CLASS
        Name = "测试群聊"

        def Click(self) -> None:
            client.current = self.Name

    result = Result()
    client._auto = Auto()
    client._activate_window = lambda *_args, **_kwargs: None
    client._main_window = object
    client.current_conversation_name = lambda: client.current
    client._find_all = lambda *_args, **_kwargs: [result]
    client._click_preserving_cursor = lambda control: control.Click()

    client._open_conversation_with_search(
        object(),
        "测试群聊",
        timeout_seconds=0.1,
        click_result=True,
    )

    assert client.current == "测试群聊"
    assert "{Enter}" not in keys


@pytest.mark.parametrize(
    ("result_count", "timeout_seconds", "message"),
    [(0, 0.0, "未找到微信好友"), (2, 0.1, "搜索结果.*不唯一")],
)
def test_keyboard_search_rejects_missing_or_duplicate_exact_results(
    result_count: int,
    timeout_seconds: float,
    message: str,
) -> None:
    value = SimpleNamespace(Value="好友A")
    search = SimpleNamespace(
        ClassName=SEARCH_EDIT_CLASS,
        GetValuePattern=lambda: value,
    )
    keys: list[str] = []
    client = object.__new__(WechatUiaClient)
    client._auto = SimpleNamespace(
        GetFocusedControl=lambda: search,
        SendKeys=lambda key, **_: keys.append(key),
    )
    client._activate_window = lambda *_, **__: None
    client._main_window = object
    result = SimpleNamespace(ClassName=SEARCH_RESULT_CLASS, Name="好友A")
    client._find_all = lambda *_, **__: [result] * result_count

    with pytest.raises(WechatUiaError, match=message):
        client._open_conversation_with_search(
            object(), "好友A", timeout_seconds=timeout_seconds
        )

    assert "{Enter}" not in keys


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
        keys: ClassVar[list[str]] = []

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


def _mention_test_client(candidates: list[object]):
    class Value:
        Value = ""

        def SetValue(self, text: str) -> None:
            self.Value = text

    value = Value()
    client = object.__new__(WechatUiaClient)

    class Input:
        AutomationId = INPUT_ID
        ClassName = INPUT_CLASS

        def GetValuePattern(self):
            return value

        def SetFocus(self) -> None:
            client._auto.focused = self

    class Auto:
        focused = None

        def SendKeys(self, text: str, **_: object) -> None:
            if text == "@":
                value.Value += "@"
            elif text == "张三":
                value.Value += "张三"
            elif text == "{Enter}":
                value.Value = "@张三 "

        def GetFocusedControl(self):
            return self.focused

    client._auto = Auto()
    client._thread_context = nullcontext
    client.focus_conversation = lambda row: None
    client._target_matches = lambda name, private: name == "测试群聊" and not private
    client._main_window = object
    client._find_unique = lambda *_, **__: Input()
    client._mention_candidates = lambda name: list(candidates)
    client._type_unicode_text = lambda text: setattr(value, "Value", value.Value + text)
    sent: list[str] = []

    def send_with_enter(_input, _value, _name, text, **_kwargs):
        sent.append(text)
        value.Value = ""

    client._send_with_enter = send_with_enter
    return client, value, sent


def test_group_first_bubble_selects_unique_real_mention() -> None:
    client, value, sent = _mention_test_client([object()])

    real = client.send_group_text_with_mention(
        ConversationRow("group", "测试群聊", private=False),
        "张三",
        "第一条",
        timeout_seconds=0.01,
    )

    assert real is True
    assert sent == ["@张三 第一条"]
    assert value.Value == ""


def test_group_real_mention_can_be_hidden_from_value_pattern() -> None:
    client, value, sent = _mention_test_client([object()])
    original_send_keys = client._auto.SendKeys

    def hide_rich_mention(text: str, **kwargs: object) -> None:
        if text == "{Enter}":
            value.Value = ""
            return
        original_send_keys(text, **kwargs)

    client._auto.SendKeys = hide_rich_mention

    real = client.send_group_text_with_mention(
        ConversationRow("group", "测试群聊", private=False),
        "张三",
        "第一条",
        timeout_seconds=0.01,
    )

    assert real is True
    assert sent == ["第一条"]
    assert value.Value == ""


def test_group_first_bubble_falls_back_to_visible_text() -> None:
    client, value, sent = _mention_test_client([])
    keys: list[str] = []
    original_send_keys = client._auto.SendKeys

    def record_keys(text: str, **kwargs: object) -> None:
        keys.append(text)
        original_send_keys(text, **kwargs)

    client._auto.SendKeys = record_keys

    real = client.send_group_text_with_mention(
        ConversationRow("group", "测试群聊", private=False),
        "张三",
        "第一条",
        timeout_seconds=0,
    )

    assert real is False
    assert sent == ["@张三\n第一条"]
    assert value.Value == ""
    assert "{Esc}" not in keys
    assert "没有唯一精确匹配" in client.mention_fallback_reason()


def test_group_mention_refuses_to_clear_concurrent_user_draft() -> None:
    client, value, sent = _mention_test_client([])
    client._type_unicode_text = lambda text: setattr(
        value, "Value", value.Value + text + "用户输入"
    )

    with pytest.raises(WechatUiaError, match="无法安全清理"):
        client.send_group_text_with_mention(
            ConversationRow("group", "测试群聊", private=False),
            "张三",
            "第一条",
            timeout_seconds=0,
        )

    assert value.Value == "@张三用户输入"
    assert sent == []
