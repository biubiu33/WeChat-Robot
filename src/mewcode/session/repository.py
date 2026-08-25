"""会话档案扫描、恢复与过期清理。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from mewcode.llm import Message

from .archive import (
    ArchiveEvent,
    ArtifactRef,
    CompactCheckpoint,
    SessionStats,
    message_from_data,
    read_events,
)
from .paths import SESSION_ID_RE, SessionPaths, paths_for


@dataclass(frozen=True)
class SessionSummary:
    session_id: str
    title: str
    last_active: datetime
    message_count: int
    model: str
    size_bytes: int


@dataclass(frozen=True)
class RestoredArchive:
    visible_events: list[ArchiveEvent]
    messages: list[Message]
    latest_checkpoint: CompactCheckpoint | None
    artifact_refs: list[ArtifactRef]
    failed_compactions: int
    last_active: datetime | None
    stats: SessionStats = field(default_factory=SessionStats)


class SessionRepository:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._sessions_dir = self._root / ".mewcode" / "sessions"
        self._cache_dir = self._root / ".mewcode" / "cache"

    def list_sessions(self) -> list[SessionSummary]:
        if not self._sessions_dir.is_dir():
            return []
        sessions: list[SessionSummary] = []
        for path in self._sessions_dir.glob("*.jsonl"):
            if not SESSION_ID_RE.fullmatch(path.stem):
                continue
            summary = self._summary_for(path)
            if summary is not None:
                sessions.append(summary)
        return sorted(sessions, key=lambda item: item.last_active, reverse=True)

    def restore(self, session_id: str) -> RestoredArchive:
        if not SESSION_ID_RE.fullmatch(session_id):
            return RestoredArchive([], [], None, [], 0, None)
        events = read_events(paths_for(self._root, session_id).archive_path)
        messages: list[Message] = []
        for event in events:
            if event.type != "message":
                continue
            message = message_from_data(event.data)
            if message is not None:
                messages.append(message)
        complete_messages = _truncate_incomplete_tool_tail(messages)
        visible_events = _visible_events(events, len(complete_messages))
        checkpoint: CompactCheckpoint | None = None
        refs: list[ArtifactRef] = []
        failures = 0
        input_tokens = 0
        output_tokens = 0
        for event in events:
            if event.type == "tool_archive":
                ref = _artifact_ref(event)
                if ref is not None:
                    refs.append(ref)
            elif event.type == "compact":
                value = _checkpoint(event)
                if value is not None:
                    checkpoint = value
                    failures = 0
            elif event.type == "compact_failure":
                count = event.data.get("failures")
                if isinstance(count, int) and count >= 0:
                    failures = count
            elif event.type == "usage":
                usage = _usage(event)
                if usage is not None:
                    input_tokens += usage[0]
                    output_tokens += usage[1]
        last_active = _last_active(events)
        return RestoredArchive(
            visible_events,
            complete_messages,
            checkpoint,
            refs,
            failures,
            last_active,
            SessionStats(
                input_tokens,
                output_tokens,
                sum(message.role == "user" for message in complete_messages),
            ),
        )

    def paths_for(self, session_id: str) -> SessionPaths:
        return paths_for(self._root, session_id)

    def delete(self, session_id: str) -> bool:
        """删除一个会话档案及其工具缓存，绝不触及长期记忆。"""
        if not SESSION_ID_RE.fullmatch(session_id):
            return False
        paths = paths_for(self._root, session_id)
        if not paths.archive_path.is_file():
            return False
        try:
            if paths.cache_dir.exists():
                shutil.rmtree(paths.cache_dir)
            paths.archive_path.unlink()
        except OSError:
            return False
        return True

    def reserve_image_bytes(
        self,
        session_id: str,
        incoming_bytes: int,
        limit_bytes: int = 256 * 1024 * 1024,
    ) -> bool:
        """Atomically clear oldest archived image data to make room for a batch."""
        if (
            not SESSION_ID_RE.fullmatch(session_id)
            or isinstance(incoming_bytes, bool)
            or not isinstance(incoming_bytes, int)
            or incoming_bytes < 0
            or isinstance(limit_bytes, bool)
            or not isinstance(limit_bytes, int)
            or limit_bytes < 0
            or incoming_bytes > limit_bytes
        ):
            return False
        path = paths_for(self._root, session_id).archive_path
        if not path.exists():
            return True
        try:
            original_lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False

        records: list[dict[str, object] | None] = []
        candidates: list[tuple[dict[str, object], int]] = []
        total = 0
        for line in original_lines:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                records.append(None)
                continue
            if not isinstance(raw, dict):
                records.append(None)
                continue
            records.append(raw)
            images = raw.get("images")
            if not isinstance(images, list):
                continue
            for image in images:
                if not isinstance(image, dict) or image.get("cleared") is True:
                    continue
                size = image.get("size_bytes")
                data = image.get("data")
                if (
                    isinstance(size, bool)
                    or not isinstance(size, int)
                    or size < 0
                    or not isinstance(data, str)
                    or not data
                ):
                    continue
                total += size
                candidates.append((image, size))
        if total + incoming_bytes <= limit_bytes:
            return True

        for image, size in candidates:
            image["data"] = ""
            image["cleared"] = True
            total -= size
            if total + incoming_bytes <= limit_bytes:
                break
        if total + incoming_bytes > limit_bytes:
            return False

        handle_id = -1
        temp_path: Path | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle_id, temp_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temp_path = Path(temp_name)
            with os.fdopen(handle_id, "w", encoding="utf-8", newline="\n") as handle:
                handle_id = -1
                for original, record in zip(original_lines, records, strict=True):
                    line = (
                        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                        if record is not None
                        else original
                    )
                    handle.write(f"{line}\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            return True
        except OSError:
            return False
        finally:
            if handle_id >= 0:
                os.close(handle_id)
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def cleanup_expired(self, now: datetime | None = None) -> list[str]:
        if not self._sessions_dir.is_dir():
            return []
        current = datetime.now() if now is None else now
        cutoff = current - timedelta(days=30)
        removed: list[str] = []
        for path in self._sessions_dir.glob("*.jsonl"):
            session_id = path.stem
            created = _session_time(session_id)
            if created is None or created >= cutoff:
                continue
            try:
                path.unlink(missing_ok=True)
                cache_path = self._cache_dir / session_id
                if cache_path.exists():
                    shutil.rmtree(cache_path)
                removed.append(session_id)
            except OSError:
                continue
        return removed

    def _summary_for(self, path: Path) -> SessionSummary | None:
        events = read_events(path)
        messages: list[Message] = []
        title = ""
        model = ""
        for event in events:
            if event.type == "message":
                message = message_from_data(event.data)
                if message is None:
                    continue
                messages.append(message)
                if message.role == "user" and not model:
                    candidate = event.data.get("model")
                    model = candidate if isinstance(candidate, str) else ""
            elif event.type == "title":
                candidate = event.data.get("title")
                if isinstance(candidate, str) and candidate.strip():
                    title = candidate.strip()
        if not title:
            title = _fallback_title(messages)
        last_active = _last_active(events)
        if last_active is None:
            try:
                last_active = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                return None
        try:
            size_bytes = path.stat().st_size
        except OSError:
            return None
        return SessionSummary(
            path.stem,
            title,
            last_active,
            len(messages),
            model,
            size_bytes,
        )


def _visible_events(
    events: list[ArchiveEvent], message_limit: int
) -> list[ArchiveEvent]:
    visible: list[ArchiveEvent] = []
    messages_seen = 0
    for event in events:
        if event.type == "message":
            if message_from_data(event.data) is None:
                continue
            messages_seen += 1
            if messages_seen > message_limit:
                continue
        if event.type in {"message", "notice", "error"}:
            visible.append(event)
    return visible


def _truncate_incomplete_tool_tail(messages: list[Message]) -> list[Message]:
    pending: set[str] = set()
    pending_start: int | None = None
    for index, message in enumerate(messages):
        if pending and message.role != "tool":
            return messages[: pending_start if pending_start is not None else index]
        if message.role == "assistant" and message.tool_calls:
            pending = {call.id for call in message.tool_calls}
            pending_start = index
        elif message.role == "tool" and pending:
            pending.difference_update(
                result.tool_call_id for result in message.tool_results
            )
            if not pending:
                pending_start = None
    if pending:
        return messages[: pending_start if pending_start is not None else len(messages)]
    return messages


def _artifact_ref(event: ArchiveEvent) -> ArtifactRef | None:
    data = event.data
    values = (
        data.get("message_index"),
        data.get("result_index"),
        data.get("relative_path"),
        data.get("preview"),
        data.get("original_length"),
    )
    if (
        not isinstance(values[0], int)
        or not isinstance(values[1], int)
        or not isinstance(values[2], str)
        or not isinstance(values[3], str)
        or not isinstance(values[4], int)
    ):
        return None
    return ArtifactRef(values[0], values[1], values[2], values[3], values[4])


def _checkpoint(event: ArchiveEvent) -> CompactCheckpoint | None:
    summary = event.data.get("summary")
    compacted_through = event.data.get("compacted_through")
    retained_from = event.data.get("retained_from")
    if (
        not isinstance(summary, str)
        or not isinstance(compacted_through, int)
        or not isinstance(retained_from, int)
        or compacted_through < 0
        or retained_from < 0
    ):
        return None
    return CompactCheckpoint(summary, compacted_through, retained_from)


def _usage(event: ArchiveEvent) -> tuple[int, int] | None:
    input_tokens = event.data.get("input_tokens")
    output_tokens = event.data.get("output_tokens")
    if (
        isinstance(input_tokens, bool)
        or isinstance(output_tokens, bool)
        or not isinstance(input_tokens, int)
        or not isinstance(output_tokens, int)
        or input_tokens < 0
        or output_tokens < 0
    ):
        return None
    return input_tokens, output_tokens


def _last_active(events: list[ArchiveEvent]) -> datetime | None:
    timestamps = [event.ts for event in events]
    return datetime.fromtimestamp(max(timestamps)) if timestamps else None


def _fallback_title(messages: list[Message]) -> str:
    for message in messages:
        if message.role == "user" and message.content.strip():
            text = " ".join(message.content.split())
            return text[:50] + ("..." if len(text) > 50 else "")
    return "未命名会话"


def _session_time(session_id: str) -> datetime | None:
    if not SESSION_ID_RE.fullmatch(session_id):
        return None
    try:
        return datetime.strptime(session_id[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return None


__all__ = ["RestoredArchive", "SessionRepository", "SessionSummary"]
