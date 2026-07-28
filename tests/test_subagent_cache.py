from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mewcode.subagent import FileReadCache, ScopedRegistry
from mewcode.tool import Registry, Result


class ReadTool:
    read_only = True

    def __init__(self) -> None:
        self.calls = 0

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "read"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        self.calls += 1
        path = Path(json.loads(args)["path"])
        return Result(path.read_text(encoding="utf-8"))


class WriteTool:
    read_only = False

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "write"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        values = json.loads(args)
        Path(values["path"]).write_text(values["content"], encoding="utf-8")
        return Result("written")


def test_cache_reuses_only_unchanged_successful_file_reads(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("first", encoding="utf-8")
    base = Registry()
    reader = ReadTool()
    base.register(reader)
    scoped = ScopedRegistry(base, {"read_file"}, cache=FileReadCache())
    raw = json.dumps({"path": str(path)})

    first = asyncio.run(scoped.execute("read_file", raw))
    second = asyncio.run(scoped.execute("read_file", raw))
    path.write_text("second value", encoding="utf-8")
    third = asyncio.run(scoped.execute("read_file", raw))

    assert first.content == second.content == "first"
    assert third.content == "second value"
    assert reader.calls == 2


def test_successful_write_invalidates_only_its_own_cache_entry(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    other = tmp_path / "other.txt"
    path.write_text("first", encoding="utf-8")
    other.write_text("other", encoding="utf-8")
    base = Registry()
    reader = ReadTool()
    base.register(reader)
    base.register(WriteTool())
    scoped = ScopedRegistry(base, {"read_file", "write_file"})
    read_path = json.dumps({"path": str(path)})
    read_other = json.dumps({"path": str(other)})

    asyncio.run(scoped.execute("read_file", read_path))
    asyncio.run(scoped.execute("read_file", read_other))
    asyncio.run(
        scoped.execute(
            "write_file", json.dumps({"path": str(path), "content": "updated"})
        )
    )
    updated = asyncio.run(scoped.execute("read_file", read_path))
    unchanged = asyncio.run(scoped.execute("read_file", read_other))

    assert updated.content == "updated"
    assert unchanged.content == "other"
    assert reader.calls == 3


def test_cache_instances_do_not_share_results(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text("value", encoding="utf-8")
    base = Registry()
    reader = ReadTool()
    base.register(reader)
    raw = json.dumps({"path": str(path)})

    asyncio.run(ScopedRegistry(base, {"read_file"}).execute("read_file", raw))
    asyncio.run(ScopedRegistry(base, {"read_file"}).execute("read_file", raw))

    assert reader.calls == 2
