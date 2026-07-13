from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from . import Result, error_result, parse_arguments, require_string


class WriteFileTool:
    read_only = False

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "以 UTF-8 创建或覆盖文本文件，并自动创建父目录。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目标文件路径"},
                "content": {"type": "string", "description": "要写入的完整内容"},
            },
            "required": ["path", "content"],
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
        content, err = require_string(values, "content", allow_empty=True)
        if err:
            return err
        assert path_text is not None and content is not None
        path = Path(path_text).expanduser()

        return await asyncio.to_thread(_write_path, path, content)


def _write_path(path: Path, content: str) -> Result:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return Result(
            content=f"已写入 {path.resolve()}（{len(content.encode('utf-8'))} 字节）"
        )
    except OSError as exc:
        return error_result("write_error", f"无法写入文件 {path}: {exc}")
