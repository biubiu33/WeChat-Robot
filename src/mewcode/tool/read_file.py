from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from . import Result, error_result, parse_arguments, require_string, truncate

MAX_LINES = 2_000
MAX_CHARS = 256 * 1024


class ReadFileTool:
    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "读取 UTF-8 文本文件并返回带行号的内容。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要读取的文件路径"}
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        values, err = parse_arguments(args)
        if err:
            return err
        assert values is not None
        path_text, err = require_string(values, "path")
        if err:
            return err
        assert path_text is not None
        path = Path(path_text).expanduser()

        if not path.exists():
            return error_result("not_found", f"文件不存在: {path}")
        if not path.is_file():
            return error_result("not_a_file", f"路径不是文件: {path}")

        return await asyncio.to_thread(_read_path, path)


def _read_path(path: Path) -> Result:
    try:
        lines: list[str] = []
        was_truncated = False
        output_chars = 0
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            for number in range(1, MAX_LINES + 1):
                remaining = MAX_CHARS - output_chars
                if remaining <= 0:
                    was_truncated = True
                    break
                line = handle.readline(remaining + 1)
                if not line:
                    break
                line_too_long = len(line) > remaining
                rendered = f"{number:6d}\t{line.rstrip(chr(10)).rstrip(chr(13))}"
                lines.append(rendered)
                output_chars += len(rendered) + (1 if number > 1 else 0)
                if line_too_long:
                    was_truncated = True
                    break
            else:
                was_truncated = bool(handle.read(1))
        content, char_truncated = truncate("\n".join(lines), MAX_CHARS)
        if was_truncated and not char_truncated:
            content += "\n[truncated]"
        return Result(content=content)
    except UnicodeDecodeError:
        return error_result("decode_error", f"文件不是有效的 UTF-8 文本: {path}")
    except OSError as exc:
        return error_result("read_error", f"无法读取文件 {path}: {exc}")
