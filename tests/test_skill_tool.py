from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mewcode.skill import LoadSkillTool, SkillCatalog, SkillRuntime
from mewcode.tool import Result

from test_skill_catalog import catalog_roots, write_skill


class FakeForkExecutor:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, skill):
        self.calls.append(skill)
        return "隔离摘要"


def test_load_skill_activates_inline_and_replaces_parameters(tmp_path: Path) -> None:
    project, user, builtin = catalog_roots(tmp_path)
    write_skill(user / "review.md", name="review", body="审查：{{args}}")
    runtime = SkillRuntime(SkillCatalog.load(project, user, builtin), {"read_file"})

    result = asyncio.run(
        LoadSkillTool(runtime).execute(
            json.dumps({"name": "review", "argument": "API"})
        )
    )

    assert result == Result("审查：API")
    assert runtime.active_skills()[0].name == "review"
    assert "审查：API" in runtime.active_environment()


def test_load_skill_runs_fork_through_executor_without_main_activation(
    tmp_path: Path,
) -> None:
    project, user, builtin = catalog_roots(tmp_path)
    write_skill(user / "test.md", name="test", mode="fork", body="测试：{{args}}")
    runtime = SkillRuntime(SkillCatalog.load(project, user, builtin), {"read_file"})
    executor = FakeForkExecutor()

    result = asyncio.run(
        LoadSkillTool(runtime, executor).execute(
            json.dumps({"name": "test", "argument": "unit"})
        )
    )

    assert result == Result("隔离摘要")
    assert executor.calls[0].argument == "unit"
    assert runtime.active_skills() == ()


def test_load_skill_reports_bad_arguments_and_unknown_names(tmp_path: Path) -> None:
    project, user, builtin = catalog_roots(tmp_path)
    runtime = SkillRuntime(SkillCatalog.load(project, user, builtin), {"read_file"})
    tool = LoadSkillTool(runtime)

    missing = asyncio.run(tool.execute("{}"))
    unknown = asyncio.run(tool.execute('{"name": "missing"}'))

    assert missing.is_error and "invalid_arguments" in missing.content
    assert unknown.is_error and "skill_not_found" in unknown.content
