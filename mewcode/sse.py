from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator


@dataclass(frozen=True)
class SSEEvent:
    event: str | None
    data: str


def iter_sse_events(lines: Iterable[str]) -> Iterator[SSEEvent]:
    event: str | None = None
    data_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            if data_lines:
                yield SSEEvent(event=event, data="\n".join(data_lines))
            event = None
            data_lines = []
            continue

        if line.startswith(":"):
            continue

        field, separator, value = line.partition(":")
        if separator:
            if value.startswith(" "):
                value = value[1:]
        else:
            value = ""

        if field == "event":
            event = value
        elif field == "data":
            data_lines.append(value)

    if data_lines:
        yield SSEEvent(event=event, data="\n".join(data_lines))
