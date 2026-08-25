from __future__ import annotations

from mewcode.wechat.group_sender_ocr import GroupSenderOcr, OcrTextLine
from mewcode.wechat.models import VisibleMessage


def group_message(text: str = "@机器人 你好") -> VisibleMessage:
    return VisibleMessage(
        "message-1",
        "group-1",
        text,
        False,
        sender_name="",
        bounds=(80, 100, 260, 150),
    )


def test_assigns_unique_sender_above_uia_body_without_replacing_text() -> None:
    message = group_message()
    lines = [
        OcrTextLine("张三", 0.98, (82, 76, 125, 96)),
        OcrTextLine("@机器人 你好", 0.99, (85, 105, 250, 145)),
    ]

    [resolved] = GroupSenderOcr.assign([message], lines, (0, 0, 800, 600))

    assert resolved.text == message.text
    assert resolved.incoming is True
    assert resolved.sender_name == "张三"


def test_sender_resolution_fails_closed_for_ambiguous_names() -> None:
    message = group_message()
    lines = [
        OcrTextLine("张三", 0.96, (82, 76, 125, 96)),
        OcrTextLine("李四", 0.95, (85, 76, 128, 96)),
        OcrTextLine(message.text, 0.99, (85, 105, 250, 145)),
    ]

    [resolved] = GroupSenderOcr.assign([message], lines, (0, 0, 800, 600))

    assert resolved.sender_name == ""


def test_sender_resolution_rejects_low_confidence_or_outgoing_body() -> None:
    message = group_message()
    low_confidence = [
        OcrTextLine("张三", 0.5, (82, 76, 125, 96)),
        OcrTextLine(message.text, 0.99, (85, 105, 250, 145)),
    ]
    [unknown] = GroupSenderOcr.assign([message], low_confidence, (0, 0, 800, 600))
    outgoing_message = VisibleMessage(
        "message-2",
        "group-1",
        "机器人回复",
        False,
        bounds=(540, 100, 720, 150),
    )
    outgoing_lines = [
        OcrTextLine("机器人回复", 0.99, (550, 105, 710, 145)),
    ]
    [outgoing] = GroupSenderOcr.assign(
        [outgoing_message], outgoing_lines, (0, 0, 800, 600)
    )

    assert unknown.sender_name == ""
    assert outgoing.incoming is False
    assert outgoing.sender_name == ""
