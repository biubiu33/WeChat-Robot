from __future__ import annotations

from mewcode.prompt import render_banner


def test_render_banner_contains_identity_cwd_and_ready_line() -> None:
    banner = render_banner("0.1.0", "/tmp/mew")

    assert "MewCode v0.1.0" in banner
    assert "cwd: /tmp/mew" in banner
    assert "就绪" in banner
    assert "/\\_/\\" in banner
