"""工具结果落盘与 Prompt Context 占位文本。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from mewcode.llm import Message, ToolResult
from mewcode.session.archive import ArtifactRef


SINGLE_RESULT_LIMIT = 16_000
MESSAGE_RESULT_LIMIT = 32_000
PREVIEW_LENGTH = 1_000


class ToolArtifactStore:
    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir

    def spill(self, messages: list[Message]) -> tuple[list[Message], list[ArtifactRef]]:
        updated = list(messages)
        refs: list[ArtifactRef] = []
        for message_index, message in enumerate(messages):
            if message.role != "tool":
                continue
            sizes = [len(result.content) for result in message.tool_results]
            selected = {
                index for index, size in enumerate(sizes) if size > SINGLE_RESULT_LIMIT
            }
            total = sum(sizes)
            for index in sorted(range(len(sizes)), key=sizes.__getitem__, reverse=True):
                if total <= MESSAGE_RESULT_LIMIT:
                    break
                if index not in selected:
                    selected.add(index)
                total -= sizes[index]
            if not selected:
                continue
            results = list(message.tool_results)
            for result_index in sorted(selected):
                result = results[result_index]
                ref = self._write(message_index, result_index, result)
                if ref is None:
                    continue
                refs.append(ref)
                results[result_index] = replace(result, content=_placeholder(ref))
            updated[message_index] = replace(message, tool_results=results)
        return updated, refs

    def _write(
        self, message_index: int, result_index: int, result: ToolResult
    ) -> ArtifactRef | None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            name = f"tool-{message_index}-{result_index}.txt"
            path = self._cache_dir / name
            path.write_text(result.content, encoding="utf-8")
            return ArtifactRef(
                message_index,
                result_index,
                name,
                result.content[:PREVIEW_LENGTH],
                len(result.content),
            )
        except OSError:
            return None


def _placeholder(ref: ArtifactRef) -> str:
    return f"工具结果已归档到 .mewcode/cache/{ref.relative_path}（原始长度 {ref.original_length} 字符）。预览：\n{ref.preview}\n需要细节时请重新读取该文件。"
