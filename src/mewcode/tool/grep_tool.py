from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from . import Result, error_result, parse_arguments, require_string

MAX_MATCHES = 100
MAX_LINE_CHARS = 64 * 1024


class GrepTool:
    read_only = True

    def name(self) -> str:
        return "grep"

    def description(self) -> str:
        return "使用 Python 正则搜索文本文件，返回文件、行号和命中内容。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python 正则表达式"},
                "path": {"type": "string", "description": "可选文件或目录"},
                "glob": {"type": "string", "description": "可选文件 glob 过滤"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        values, err = parse_arguments(args)
        if err:
            return err
        assert values is not None
        pattern, err = require_string(values, "pattern")
        if err:
            return err
        path_value = values.get("path", ".")
        glob_value = values.get("glob")
        if not isinstance(path_value, str) or not path_value:
            return error_result("invalid_arguments", "参数 path 必须是非空字符串")
        if glob_value is not None and not isinstance(glob_value, str):
            return error_result("invalid_arguments", "参数 glob 必须是字符串")
        assert pattern is not None
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return error_result("invalid_regex", f"无效正则表达式: {exc}")

        root = Path(path_value).expanduser()
        if not root.exists():
            return error_result("not_found", f"搜索路径不存在: {root}")
        files = [root] if root.is_file() else root.rglob("*")
        matches: list[str] = []
        truncated = False
        skipped_long_line = False

        for file_index, file_path in enumerate(files, start=1):
            if file_index % 25 == 0:
                await asyncio.sleep(0)
            if not file_path.is_file():
                continue
            relative = (
                file_path.name
                if root.is_file()
                else file_path.relative_to(root).as_posix()
            )
            if glob_value and not Path(relative).match(glob_value):
                continue
            try:
                with file_path.open("r", encoding="utf-8", errors="strict") as handle:
                    line_number = 0
                    while True:
                        line = handle.readline(MAX_LINE_CHARS + 1)
                        if not line:
                            break
                        line_number += 1
                        if len(line) > MAX_LINE_CHARS and not line.endswith("\n"):
                            skipped_long_line = True
                            while line and not line.endswith("\n"):
                                line = handle.readline(MAX_LINE_CHARS + 1)
                            continue
                        clean = line.rstrip("\r\n")
                        if regex.search(clean):
                            matches.append(f"{relative}:{line_number}:{clean}")
                            if len(matches) > MAX_MATCHES:
                                truncated = True
                                break
                        if line_number % 500 == 0:
                            await asyncio.sleep(0)
            except (OSError, UnicodeDecodeError):
                continue
            if truncated:
                break

        if not matches:
            suffix = "；存在超长行未完整搜索" if skipped_long_line else ""
            return Result(content=f"没有匹配的内容{suffix}")
        content = "\n".join(matches[:MAX_MATCHES])
        if truncated:
            content += "\n[truncated]"
        if skipped_long_line:
            content += "\n[存在超长行未完整搜索]"
        return Result(content=content)
