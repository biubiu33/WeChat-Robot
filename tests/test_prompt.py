from __future__ import annotations

import datetime as dt

from mewcode.prompt import (
    EXECUTE_DIRECTIVE,
    Module,
    assemble_system,
    build_system_prompt,
    gather_environment,
    optional_modules,
    plan_reminder,
    render_banner,
)


def test_render_banner_contains_identity_cwd_and_ready_line() -> None:
    banner = render_banner("0.1.0", "/tmp/mew")

    assert "MewCode v0.1.0" in banner
    assert "cwd: /tmp/mew" in banner
    assert "就绪" in banner
    assert "/\\_/\\" in banner


def test_system_prompt_has_stable_order_and_key_agent_rules() -> None:
    prompt = build_system_prompt()
    headings = [
        "## 角色设定",
        "## 行为准则",
        "## 工具使用指南",
        "## 代码质量规范",
        "## 安全边界",
        "## 任务执行模式",
        "## 输出风格",
    ]

    assert [prompt.index(heading) for heading in headings] == sorted(
        prompt.index(heading) for heading in headings
    )
    assert "\n\n## " in prompt
    assert "优先使用最匹配的专用工具" in prompt
    assert "编辑已有文件前必须先使用 `read_file`" in prompt
    assert "用户使用中文时使用中文" in prompt


def test_assemble_system_skips_empty_slots_and_is_deterministic() -> None:
    modules = [
        Module("后", 20, "后面的内容"),
        Module("空", 15, ""),
        Module("前", 10, "前面的内容"),
    ]

    rendered = assemble_system(modules)

    assert rendered == "## 前\n前面的内容\n\n## 后\n后面的内容"
    assert "## 空" not in rendered
    assert "\n\n\n" not in rendered
    assert build_system_prompt() == build_system_prompt()
    assert all(not module.content for module in optional_modules())


def test_build_system_prompt_injects_instructions_and_memory() -> None:
    prompt = build_system_prompt("项目规则", "长期偏好")

    assert "## 自定义指令\n项目规则" in prompt
    assert "## 长期记忆\n长期偏好" in prompt
    assert prompt.index("项目规则") < prompt.index("长期偏好")


def test_build_system_prompt_injects_skill_metadata_without_sop() -> None:
    prompt = build_system_prompt(skills="- `review`: 审查改动")

    assert "## 可用 Skill\n- `review`: 审查改动" in prompt
    assert "完整 SOP 正文" not in prompt


def test_environment_is_dynamic_and_degrades_without_git(tmp_path) -> None:
    environment = gather_environment(
        "0.1.0",
        "test-model",
        cwd=tmp_path,
        today=dt.date(2026, 7, 14),
    )

    rendered = environment.render()
    assert f"工作目录: {tmp_path.resolve()}" in rendered
    assert "平台:" in rendered
    assert "当前日期: 2026-07-14" in rendered
    assert "应用版本: 0.1.0" in rendered
    assert "当前模型: test-model" in rendered
    assert "Git 状态:" not in rendered
    assert str(tmp_path) not in build_system_prompt()
    assert "2026-07-14" not in build_system_prompt()


def test_plan_reminders_are_tagged_and_execute_directive_is_available() -> None:
    full = plan_reminder(True)
    concise = plan_reminder(False)

    assert full.startswith("<system-reminder>\n")
    assert full.endswith("\n</system-reminder>")
    assert "read_file、glob、grep" in full
    assert "只可使用只读工具" in concise
    assert len(concise) < len(full)
    assert EXECUTE_DIRECTIVE == "请按上面的计划开始执行。"
