from __future__ import annotations

import time
from pathlib import Path

import pytest

from mewcode.skill import (
    SkillCatalog,
    SkillMode,
    SkillParseError,
    SkillSource,
    parse_skill,
)


def write_skill(
    path: Path,
    *,
    name: str = "demo",
    description: str = "演示 Skill",
    tools: str = "[read_file]",
    mode: str = "inline",
    history: str = "none",
    model: str | None = None,
    body: str = "处理参数：{{args}}",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    model_line = "" if model is None else f"model: {model}\n"
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"allowed_tools: {tools}\n"
        f"mode: {mode}\n"
        f"fork_history: {history}\n"
        f"{model_line}"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


def catalog_roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    user = tmp_path / "user-skills"
    builtin = tmp_path / "builtins"
    return project, user, builtin


def test_parse_single_file_metadata_and_parameter_replacement(tmp_path: Path) -> None:
    entry = tmp_path / "demo.md"
    write_skill(entry, model="demo-model")

    skill = parse_skill(entry, SkillSource.USER)

    assert skill.metadata.name == "demo"
    assert skill.metadata.mode is SkillMode.INLINE
    assert skill.metadata.allowed_tools == frozenset({"read_file"})
    assert skill.metadata.model == "demo-model"
    assert skill.load_instruction("检查 src") == "处理参数：检查 src"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": "Bad Name"}, "名称"),
        ({"description": ""}, "description"),
        ({"tools": "read_file"}, "allowed_tools"),
        ({"mode": "shared"}, "mode"),
        ({"history": "full"}, "fork_history"),
        ({"body": ""}, "正文"),
    ],
)
def test_parse_rejects_invalid_metadata(
    tmp_path: Path, kwargs: dict[str, str], message: str
) -> None:
    entry = tmp_path / "broken.md"
    write_skill(entry, **kwargs)

    with pytest.raises(SkillParseError, match=message):
        parse_skill(entry, SkillSource.USER)


def test_parse_rejects_missing_or_invalid_frontmatter(tmp_path: Path) -> None:
    entry = tmp_path / "broken.md"
    entry.write_text("正文", encoding="utf-8")

    with pytest.raises(SkillParseError, match="frontmatter"):
        parse_skill(entry, SkillSource.USER)

    entry.write_text("---\nname: [\n---\n正文", encoding="utf-8")
    with pytest.raises(SkillParseError, match="YAML"):
        parse_skill(entry, SkillSource.USER)


def test_catalog_discovers_single_and_directory_skills(tmp_path: Path) -> None:
    project, user, builtin = catalog_roots(tmp_path)
    write_skill(user / "single.md", name="single")
    write_skill(user / "package" / "SKILL.md", name="package")
    (user / "package" / "reference.md").write_text("辅助文档", encoding="utf-8")

    catalog = SkillCatalog.load(project, user, builtin)

    assert [skill.metadata.name for skill in catalog.effective()] == [
        "package",
        "single",
    ]
    assert catalog.get("package").package_root == user / "package"  # type: ignore[union-attr]


def test_catalog_applies_project_user_builtin_precedence(tmp_path: Path) -> None:
    project, user, builtin = catalog_roots(tmp_path)
    write_skill(builtin / "same.md", name="same", description="内置")
    write_skill(user / "same.md", name="same", description="用户")
    write_skill(
        project / ".mewcode" / "skills" / "same.md", name="same", description="项目"
    )

    catalog = SkillCatalog.load(project, user, builtin)

    skill = catalog.get("same")
    assert skill is not None
    assert skill.metadata.description == "项目"
    assert skill.source is SkillSource.PROJECT


def test_catalog_skips_invalid_and_duplicate_entries(tmp_path: Path) -> None:
    project, user, builtin = catalog_roots(tmp_path)
    write_skill(user / "valid.md", name="valid")
    write_skill(user / "one.md", name="duplicate")
    write_skill(user / "two" / "SKILL.md", name="duplicate")
    (user / "invalid.md").write_text("not a skill", encoding="utf-8")

    catalog = SkillCatalog.load(project, user, builtin)

    assert [skill.metadata.name for skill in catalog.effective()] == [
        "duplicate",
        "valid",
    ]
    messages = [diagnostic.message for diagnostic in catalog.diagnostics()]
    assert any("frontmatter" in message for message in messages)
    assert any("重复" in message for message in messages)


def test_catalog_detects_and_applies_changes(tmp_path: Path) -> None:
    project, user, builtin = catalog_roots(tmp_path)
    entry = user / "demo.md"
    write_skill(entry, name="demo", description="旧说明")
    catalog = SkillCatalog.load(project, user, builtin)

    assert catalog.has_changed() is False
    time.sleep(0.01)
    write_skill(entry, name="demo", description="新说明")
    assert catalog.has_changed() is True
    assert catalog.refresh_if_changed() is True
    assert catalog.get("demo").metadata.description == "新说明"  # type: ignore[union-attr]

    entry.unlink()
    assert catalog.refresh_if_changed() is True
    assert catalog.get("demo") is None
