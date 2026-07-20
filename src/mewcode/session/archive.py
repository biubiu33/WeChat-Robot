"""JSONL 会话档案事件、编码与安全追加。"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mewcode.llm import Message, ToolCall, ToolResult


EventType = Literal[
    "message",
    "notice",
    "error",
    "title",
    "tool_archive",
    "compact",
    "compact_failure",
    "usage",
]


@dataclass(frozen=True)
class ArchiveEvent:
    type: EventType
    ts: int
    data: dict[str, object]


@dataclass(frozen=True)
class ArtifactRef:
    message_index: int
    result_index: int
    relative_path: str
    preview: str
    original_length: int


@dataclass(frozen=True)
class CompactCheckpoint:
    summary: str
    compacted_through: int
    retained_from: int


@dataclass
class SessionStats:
    input_tokens: int = 0
    output_tokens: int = 0
    turns: int = 0


def event_to_dict(event: ArchiveEvent) -> dict[str, object]:
    return {"type": event.type, "ts": event.ts, **event.data}


def event_from_dict(raw: object) -> ArchiveEvent | None:
    if not isinstance(raw, dict):
        return None
    event_type = raw.get("type")
    timestamp = raw.get("ts")
    if event_type not in {
        "message",
        "notice",
        "error",
        "title",
        "tool_archive",
        "compact",
        "compact_failure",
        "usage",
    } or not isinstance(timestamp, int):
        return None
    data = {key: value for key, value in raw.items() if key not in {"type", "ts"}}
    return ArchiveEvent(event_type, timestamp, data)  # type: ignore[arg-type]


def message_to_data(message: Message, *, model: str = "") -> dict[str, object]:
    data: dict[str, object] = {
        "role": message.role,
        "content": message.content,
        "tool_calls": [
            {"id": call.id, "name": call.name, "input": call.input}
            for call in message.tool_calls
        ],
        "tool_results": [
            {
                "tool_call_id": result.tool_call_id,
                "content": result.content,
                "is_error": result.is_error,
            }
            for result in message.tool_results
        ],
    }
    if model:
        data["model"] = model
    return data


def message_from_data(data: dict[str, object]) -> Message | None:
    role = data.get("role")
    if role not in {"user", "assistant", "tool"}:
        return None
    content = data.get("content", "")
    if not isinstance(content, str):
        return None
    calls = _tool_calls(data.get("tool_calls"))
    results = _tool_results(data.get("tool_results"))
    if calls is None or results is None:
        return None
    return Message(role=role, content=content, tool_calls=calls, tool_results=results)


def read_events(path: Path) -> list[ArchiveEvent]:
    events: list[ArchiveEvent] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event = event_from_dict(raw)
                if event is not None:
                    events.append(event)
    except OSError:
        return []
    return events


class ArchiveWriter:
    """以单行 JSON 追加档案，写入失败只能降级。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._closed = False
        self._first_user_written = any(
            event.type == "message"
            and event.data.get("role") == "user"
            and isinstance(event.data.get("model"), str)
            for event in read_events(path)
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._handle = path.open("a", encoding="utf-8", newline="\n")
        except OSError:
            self._handle = None
            self._warn(f"无法写入会话档案: {path}")

    def append_message(self, message: Message, *, model: str = "") -> None:
        record_model = ""
        if message.role == "user" and model and not self._first_user_written:
            record_model = model
            self._first_user_written = True
        self.append(
            ArchiveEvent(
                "message", _now(), message_to_data(message, model=record_model)
            )
        )

    def append_title(self, title: str) -> None:
        self.append(ArchiveEvent("title", _now(), {"title": title}))

    def append_tool_archive(self, ref: ArtifactRef) -> None:
        self.append(
            ArchiveEvent(
                "tool_archive",
                _now(),
                {
                    "message_index": ref.message_index,
                    "result_index": ref.result_index,
                    "relative_path": ref.relative_path,
                    "preview": ref.preview,
                    "original_length": ref.original_length,
                },
            )
        )

    def append_compact(self, checkpoint: CompactCheckpoint) -> None:
        self.append(
            ArchiveEvent(
                "compact",
                _now(),
                {
                    "summary": checkpoint.summary,
                    "compacted_through": checkpoint.compacted_through,
                    "retained_from": checkpoint.retained_from,
                },
            )
        )

    def append_compact_failure(self, failures: int) -> None:
        self.append(ArchiveEvent("compact_failure", _now(), {"failures": failures}))

    def append_visible(self, event_type: Literal["notice", "error"], text: str) -> None:
        self.append(ArchiveEvent(event_type, _now(), {"text": text}))

    def append_usage(self, input_tokens: int, output_tokens: int) -> None:
        if (
            isinstance(input_tokens, bool)
            or isinstance(output_tokens, bool)
            or not isinstance(input_tokens, int)
            or not isinstance(output_tokens, int)
            or input_tokens < 0
            or output_tokens < 0
        ):
            raise ValueError("Token usage 必须是非负整数")
        self.append(
            ArchiveEvent(
                "usage",
                _now(),
                {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            )
        )

    def append(self, event: ArchiveEvent) -> None:
        line = json.dumps(
            event_to_dict(event), ensure_ascii=False, separators=(",", ":")
        )
        with self._lock:
            if self._closed or self._handle is None:
                return
            try:
                self._handle.write(f"{line}\n")
                self._handle.flush()
                os.fsync(self._handle.fileno())
            except OSError as exc:
                self._warn(f"写入会话档案失败: {exc}")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._handle is None:
                return
            try:
                self._handle.close()
            except OSError:
                return

    def __enter__(self) -> ArchiveWriter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _warn(self, message: str) -> None:
        print(f"[session] warn: {message}", file=sys.stderr)


def _now() -> int:
    return int(time.time())


def _tool_calls(raw: object) -> list[ToolCall] | None:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    calls: list[ToolCall] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        call_id, name, input_text = item.get("id"), item.get("name"), item.get("input")
        if not all(isinstance(value, str) for value in (call_id, name, input_text)):
            return None
        calls.append(ToolCall(call_id, name, input_text))
    return calls


def _tool_results(raw: object) -> list[ToolResult] | None:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return None
    results: list[ToolResult] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        call_id, content, is_error = (
            item.get("tool_call_id"),
            item.get("content"),
            item.get("is_error", False),
        )
        if (
            not isinstance(call_id, str)
            or not isinstance(content, str)
            or not isinstance(is_error, bool)
        ):
            return None
        results.append(ToolResult(call_id, content, is_error))
    return results


__all__ = [
    "ArchiveEvent",
    "ArchiveWriter",
    "ArtifactRef",
    "CompactCheckpoint",
    "SessionStats",
    "event_from_dict",
    "event_to_dict",
    "message_from_data",
    "message_to_data",
    "read_events",
]
