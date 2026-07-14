from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import wraps
import json
import os
import sys
from pathlib import Path
from typing import Any, TypeVar

import pytest

from mewcode.tool import Registry, Result, new_default_registry

F = TypeVar("F", bound=Callable[..., Any])


def async_test(func: F) -> F:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(func(*args, **kwargs))

    return wrapper  # type: ignore[return-value]


def args(**values: object) -> str:
    return json.dumps(values, ensure_ascii=False)


def test_default_registry_exports_six_tools_in_stable_order() -> None:
    registry = new_default_registry()
    definitions = registry.definitions()

    assert [definition.name for definition in definitions] == [
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "glob",
        "grep",
    ]
    assert all(definition.description for definition in definitions)
    assert all(definition.input_schema["type"] == "object" for definition in definitions)
    assert registry.get("read_file") is not None
    assert registry.get("missing") is None
    assert [definition.name for definition in registry.read_only_definitions()] == [
        "read_file",
        "glob",
        "grep",
    ]
    assert registry.is_read_only("read_file")
    assert registry.is_read_only("glob")
    assert registry.is_read_only("grep")
    assert not registry.is_read_only("write_file")
    assert not registry.is_read_only("bash")
    assert not registry.is_read_only("missing")


def test_tool_descriptions_reinforce_specialized_tool_rules() -> None:
    registry = new_default_registry()
    edit_file = registry.get("edit_file")
    bash = registry.get("bash")

    assert edit_file is not None and bash is not None
    assert "先使用 read_file" in edit_file.description()
    assert "优先使用 read_file、glob、grep" in bash.description()


def test_registry_rejects_duplicate_names() -> None:
    registry = Registry()
    tool = new_default_registry().get("read_file")
    assert tool is not None
    registry.register(tool)

    with pytest.raises(ValueError, match="已注册"):
        registry.register(tool)


@async_test
async def test_registry_returns_structured_errors_and_timeout() -> None:
    class BrokenTool:
        def name(self) -> str:
            return "broken"

        def description(self) -> str:
            return "测试异常"

        def parameters(self) -> dict[str, object]:
            return {"type": "object", "properties": {}}

        async def execute(self, raw: str) -> Result:
            raise RuntimeError("boom")

    class SlowTool(BrokenTool):
        def name(self) -> str:
            return "slow"

        async def execute(self, raw: str) -> Result:
            await asyncio.sleep(1)
            return Result("done")

    registry = Registry()
    registry.register(BrokenTool())
    registry.register(SlowTool())

    unknown = await registry.execute("missing", "{}")
    broken = await registry.execute("broken", "{}")
    timed_out = await registry.execute("slow", "", timeout=0.01)
    assert unknown.is_error and "unknown_tool" in unknown.content
    assert broken.is_error and "internal_error" in broken.content
    assert timed_out.is_error and "timeout" in timed_out.content


@async_test
async def test_read_write_and_edit_file(tmp_path: Path) -> None:
    registry = new_default_registry()
    path = tmp_path / "nested" / "中文.txt"

    written = await registry.execute(
        "write_file", args(path=str(path), content="你好\nold\n")
    )
    read = await registry.execute("read_file", args(path=str(path)))
    edited = await registry.execute(
        "edit_file",
        args(path=str(path), old_string="old", new_string="MewCode"),
    )

    assert not written.is_error
    assert "1\t你好" in read.content
    assert not edited.is_error
    assert path.read_text(encoding="utf-8") == "你好\nMewCode\n"


@async_test
async def test_file_tools_report_boundaries(tmp_path: Path) -> None:
    registry = new_default_registry()
    missing = tmp_path / "missing.txt"
    repeated = tmp_path / "repeated.txt"
    repeated.write_text("same same", encoding="utf-8")
    binary = tmp_path / "binary.txt"
    binary.write_bytes(b"\xff\xfe")

    not_found = await registry.execute("read_file", args(path=str(missing)))
    bad_encoding = await registry.execute("read_file", args(path=str(binary)))
    zero = await registry.execute(
        "edit_file",
        args(path=str(repeated), old_string="absent", new_string="x"),
    )
    many = await registry.execute(
        "edit_file",
        args(path=str(repeated), old_string="same", new_string="x"),
    )

    assert not_found.is_error and "not_found" in not_found.content
    assert bad_encoding.is_error and "decode_error" in bad_encoding.content
    assert zero.is_error and "未找到匹配" in zero.content
    assert many.is_error and "匹配到 2 处" in many.content
    assert repeated.read_text(encoding="utf-8") == "same same"


@async_test
async def test_read_file_truncates_large_content(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    path.write_text("\n".join(f"line {i}" for i in range(2_100)), encoding="utf-8")

    result = await new_default_registry().execute("read_file", args(path=str(path)))

    assert not result.is_error
    assert "[truncated]" in result.content
    assert "line 2099" not in result.content


@async_test
async def test_read_file_truncates_one_oversized_line(tmp_path: Path) -> None:
    path = tmp_path / "long-line.txt"
    path.write_text("x" * 400_000, encoding="utf-8")

    result = await new_default_registry().execute("read_file", args(path=str(path)))

    assert not result.is_error
    assert len(result.content) <= 256 * 1024
    assert result.content.endswith("[truncated]")


@async_test
async def test_bash_returns_output_exit_code_and_failure() -> None:
    registry = new_default_registry()
    success_command = f'"{sys.executable}" -c "print(123)"'
    failure_command = f'"{sys.executable}" -c "import sys; print(\'bad\', file=sys.stderr); sys.exit(7)"'

    success = await registry.execute("bash", args(command=success_command))
    failure = await registry.execute("bash", args(command=failure_command))

    assert not success.is_error
    assert "123" in success.content and "exit_code: 0" in success.content
    assert failure.is_error
    assert "bad" in failure.content and "exit_code: 7" in failure.content


@async_test
async def test_bash_timeout_returns_error() -> None:
    command = f'"{sys.executable}" -c "import time; time.sleep(5)"'

    result = await new_default_registry().execute(
        "bash", args(command=command), timeout=0.05
    )

    assert result.is_error
    assert "timeout" in result.content


@async_test
async def test_bash_truncates_long_output() -> None:
    command = f'"{sys.executable}" -c "print(\'x\' * 50000)"'

    result = await new_default_registry().execute("bash", args(command=command))

    assert not result.is_error
    assert "[truncated]" in result.content
    assert len(result.content) < 31_000


@async_test
async def test_glob_and_grep(tmp_path: Path) -> None:
    registry = new_default_registry()
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("# 标记\nneedle = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "b.txt").write_text("needle\n", encoding="utf-8")

    globbed = await registry.execute(
        "glob", args(path=str(tmp_path), pattern="**/*.py")
    )
    searched = await registry.execute(
        "grep", args(path=str(tmp_path), pattern="needle", glob="**/*.py")
    )
    empty = await registry.execute(
        "grep", args(path=str(tmp_path), pattern="absent")
    )
    invalid = await registry.execute("grep", args(path=str(tmp_path), pattern="["))

    assert globbed.content == "pkg/a.py"
    assert "pkg/a.py:2:needle = 1" in searched.content
    assert "b.txt" not in searched.content
    assert not empty.is_error and "没有匹配" in empty.content
    assert invalid.is_error and "invalid_regex" in invalid.content


@async_test
async def test_relative_paths_use_process_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    registry = new_default_registry()

    await registry.execute("write_file", args(path="local.txt", content="cwd"))
    result = await registry.execute("read_file", args(path="local.txt"))

    assert (tmp_path / "local.txt").exists()
    assert "cwd" in result.content
    assert os.getcwd() == str(tmp_path)
