from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable


@dataclass
class ConsoleIO:
    input: Callable[[str], str]
    write: Callable[[str], None]
    flush: Callable[[], None]


def default_console_io() -> ConsoleIO:
    configure_utf8_stdio()
    return ConsoleIO(
        input=input,
        write=sys.stdout.write,
        flush=sys.stdout.flush,
    )


def configure_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
