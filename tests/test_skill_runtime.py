from __future__ import annotations

import time
from pathlib import Path

import pytest

from mewcode.skill import SkillCatalog, SkillRuntime, SkillValidationError

from test_skill_catalog import catalog_roots, write_skill


def runtime(tmp_path: Path) -> tuple[SkillRuntime, Path]:
    project, user, builtin = catalog_roots(tmp_path)
    write_skill(user / "review.md", name="review", tools="[read_file, grep]")
    write_skill(
        user / "test.md",
        name="test",
        tools="[bash]",
        model="skill-model",
        body="运行：{{args}}",
    )
    catalog = SkillCatalog.load(project, user, builtin)
    return SkillRuntime(catalog, {"read_file", "grep", "bash"}), user


def test_runtime_renders_available_and_active_skill_context(tmp_path: Path) -> None:
    skills, _ = runtime(tmp_path)

    assert "`review`: 演示 Skill" in skills.available_prompt()
    assert "处理参数" not in skills.available_prompt()
    review = skills.activate_inline("review", "检查 API")
    test = skills.activate_inline("test", "unit")

    assert review.name == "review"
    assert test.instruction == "运行：unit"
    environment = skills.active_environment()
    assert environment.startswith("# 已激活 Skill")
    assert "## review" in environment and "处理参数：检查 API" in environment
    assert "## test" in environment and "运行：unit" in environment
    assert skills.ordinary_allowed_tools() == frozenset({"read_file", "grep", "bash"})
    assert skills.requested_model() == "skill-model"


def test_runtime_rejects_unknown_tools_and_model_conflicts(tmp_path: Path) -> None:
    project, user, builtin = catalog_roots(tmp_path)
    write_skill(user / "bad.md", name="bad", tools="[missing]")
    catalog = SkillCatalog.load(project, user, builtin)

    with pytest.raises(SkillValidationError, match="missing"):
        SkillRuntime(catalog, {"read_file"})

    (user / "bad.md").unlink()
    write_skill(user / "first.md", name="first", model="one")
    write_skill(user / "second.md", name="second", model="two")
    skills = SkillRuntime(SkillCatalog.load(project, user, builtin), {"read_file"})
    skills.activate_inline("first", "")
    with pytest.raises(SkillValidationError, match="冲突"):
        skills.activate_inline("second", "")


def test_runtime_prepares_fork_without_activating_main_context(tmp_path: Path) -> None:
    skills, _ = runtime(tmp_path)

    fork = skills.prepare_fork("test", "selected")

    assert fork.argument == "selected"
    assert skills.active_skills() == ()
    assert skills.active_environment() == ""
    assert skills.ordinary_allowed_tools() is None


def test_runtime_clear_and_refresh_rebinds_or_removes_active_skills(
    tmp_path: Path,
) -> None:
    skills, user = runtime(tmp_path)
    skills.activate_inline("review", "first")
    time.sleep(0.01)
    write_skill(user / "review.md", name="review", body="更新：{{args}}")

    refreshed = skills.refresh()

    assert refreshed.changed is True
    assert skills.active_skills()[0].instruction == "更新：first"
    (user / "review.md").unlink()
    refreshed = skills.refresh()
    assert refreshed.removed == ("review",)
    assert skills.active_skills() == ()

    skills.clear()
    assert skills.active_skills() == ()
