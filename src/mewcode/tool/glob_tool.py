from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from . import Result, error_result, parse_arguments, require_string

MAX_MATCHES = 100


class GlobTool:
    def name(self) -> str:
        return "glob"

    def description(self) -> str:
        return "按 glob 模式查找文件并返回排序后的路径列表。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "glob 模式，如 **/*.py"},
                "path": {"type": "string", "description": "可选搜索根目录"},
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
        root_value = values.get("path", ".")
        if not isinstance(root_value, str) or not root_value:
            return error_result("invalid_arguments", "参数 path 必须是非空字符串")
        assert pattern is not None
        root = Path(root_value).expanduser()
        if not root.exists():
            return error_result("not_found", f"搜索路径不存在: {root}")
        if not root.is_dir():
            return error_result("not_a_directory", f"搜索路径不是目录: {root}")

        try:
            paths: list[str] = []
            truncated = False
            for index, path in enumerate(root.glob(pattern), start=1):
                if index % 100 == 0:
                    await asyncio.sleep(0)
                if not path.is_file():
                    continue
                paths.append(path.relative_to(root).as_posix())
                if len(paths) > MAX_MATCHES:
                    truncated = True
                    break
            paths = sorted(paths[:MAX_MATCHES])
        except (OSError, ValueError) as exc:
            return error_result("glob_error", f"文件查找失败: {exc}")

        if not paths:
            return Result(content="没有匹配的文件")
        content = "\n".join(paths)
        if truncated:
            content += "\n[truncated]"
        return Result(content=content)
