from __future__ import annotations

from mewcode.prompt import SYSTEM_PROMPT, render_banner


def test_render_banner_contains_identity_cwd_and_ready_line() -> None:
    banner = render_banner("0.1.0", "/tmp/mew")

    assert "MewCode v0.1.0" in banner
    assert "cwd: /tmp/mew" in banner
    assert "就绪" in banner
    assert "/\\_/\\" in banner


def test_system_prompt_describes_agent_tool_behavior() -> None:
    assert "AI 编码助手" in SYSTEM_PROMPT
    assert "工具" in SYSTEM_PROMPT
    assert "不要编造工具结果" in SYSTEM_PROMPT
    assert "只进行纯文本对话" not in SYSTEM_PROMPT
