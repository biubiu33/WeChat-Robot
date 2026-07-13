from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from . import Result, error_result, parse_arguments, require_string


class EditFileTool:
    read_only = False

    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return "在 UTF-8 文件中唯一匹配 old_string，并替换为 new_string。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要修改的文件路径"},
                "old_string": {"type": "string", "description": "必须唯一匹配的原文"},
                "new_string": {"type": "string", "description": "替换后的新文本"},
            },
            "required": ["path", "old_string", "new_string"],
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
        old, err = require_string(values, "old_string")
        if err:
            return err
        new, err = require_string(values, "new_string", allow_empty=True)
        if err:
            return err
        assert path_text is not None and old is not None and new is not None
        path = Path(path_text).expanduser()

        return await asyncio.to_thread(_edit_path, path, old, new)


def _edit_path(path: Path, old: str, new: str) -> Result:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return error_result("not_found", f"文件不存在: {path}")
    except UnicodeDecodeError:
        return error_result("decode_error", f"文件不是有效的 UTF-8 文本: {path}")
    except OSError as exc:
        return error_result("read_error", f"无法读取文件 {path}: {exc}")

    count = content.count(old)
    if count == 0:
        return error_result("not_found", "未找到匹配的 old_string，文件未修改")
    if count > 1:
        return error_result(
            "not_unique",
            f"匹配到 {count} 处，old_string 不唯一，请提供更长上下文",
        )

    try:
        path.write_text(content.replace(old, new, 1), encoding="utf-8")
        return Result(content=f"已修改 {path.resolve()}（替换 1 处）")
    except OSError as exc:
        return error_result("write_error", f"无法写回文件 {path}: {exc}")
