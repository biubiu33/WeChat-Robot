from __future__ import annotations

from pathlib import Path

from mewcode.memory.instructions import InstructionLoader


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_loader_merges_layers_by_priority_and_caches_result(tmp_path: Path) -> None:
    root = tmp_path / "project"
    home = tmp_path / "home"
    write(root / "MEWCODE.md", "项目根规则")
    write(root / ".mewcode" / "MEWCODE.md", "项目配置规则")
    write(home / ".mewcode" / "MEWCODE.md", "用户规则")
    loader = InstructionLoader(root, home)

    first = loader.load_once()
    write(root / "MEWCODE.md", "已修改但不应读取")
    second = loader.load_once()

    assert first is second
    assert first.content.split("\n\n") == ["项目根规则", "项目配置规则", "用户规则"]


def test_loader_expands_include_and_blocks_cycle_escape_and_binary(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    home = tmp_path / "home"
    write(
        root / "MEWCODE.md", "开始\n@include <rules/a.md>\n@include <../outside.md>\n"
    )
    write(root / "rules" / "a.md", "A\n@include <b.md>\n")
    write(root / "rules" / "b.md", "B\n@include <a.md>\n")
    (root / "rules" / "binary.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "rules" / "binary.md").write_bytes(b"\0binary")
    write(root / ".mewcode" / "MEWCODE.md", "@include <../rules/binary.md>\n")

    bundle = InstructionLoader(root, home).load_once()

    assert "开始" in bundle.content
    assert "A" in bundle.content and "B" in bundle.content
    assert "outside" not in bundle.content
    assert any("环路" in warning for warning in bundle.warnings)
    assert any("超出允许范围" in warning for warning in bundle.warnings)
    assert any("二进制" in warning for warning in bundle.warnings)


def test_loader_rejects_sixth_include_level_and_midline_directive(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    write(
        root / "MEWCODE.md",
        "文字 @include <rules/a.md> 不展开\n@include <rules/d1.md>\n",
    )
    write(root / "rules" / "a.md", "不应出现")
    for index in range(1, 6):
        write(root / "rules" / f"d{index}.md", f"@include <d{index + 1}.md>\n")
    write(root / "rules" / "d6.md", "too deep")

    bundle = InstructionLoader(root, tmp_path / "home").load_once()

    assert "文字 @include <rules/a.md> 不展开" in bundle.content
    assert "too deep" not in bundle.content
    assert any("最大嵌套深度" in warning for warning in bundle.warnings)
