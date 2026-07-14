from __future__ import annotations

from mewcode.llm import Request, System
from mewcode.llm.anthropic_provider import to_anthropic_system


def test_anthropic_marks_stable_system_block_for_cache_only() -> None:
    request = Request(system=System(stable="稳定提示", environment="环境信息"))

    assert to_anthropic_system(request) == [
        {
            "type": "text",
            "text": "稳定提示",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "环境信息"},
    ]
