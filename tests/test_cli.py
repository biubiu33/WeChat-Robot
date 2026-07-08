from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from mewcode import cli
from mewcode.models import ProviderProfile


def write_config(path: Path) -> Path:
    path.write_text(
        """
providers:
  - name: openai
    protocol: openai
    model: gpt-test
    base_url: https://openai.test/v1
    api_key: sk-cli-secret
  - name: claude
    protocol: anthropic
    model: claude-test
    base_url: https://anthropic.test/v1
    api_key: sk-ant-secret
""",
        encoding="utf-8",
    )
    return path


def test_cli_uses_selected_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = write_config(tmp_path / "mewcode.yaml")
    seen: dict[str, object] = {}

    def fake_create_provider(profile: ProviderProfile) -> object:
        seen["profile"] = profile
        return object()

    def fake_run_chat(provider: object, profile_name: str) -> int:
        seen["provider"] = provider
        seen["profile_name"] = profile_name
        return 0

    monkeypatch.setattr(cli, "create_provider", fake_create_provider)
    monkeypatch.setattr(cli, "run_chat", fake_run_chat)

    result = cli.main(["--config", str(config_path), "--profile", "claude"])

    assert result == 0
    assert seen["profile_name"] == "claude"
    assert isinstance(seen["profile"], ProviderProfile)
    assert seen["profile"].protocol == "anthropic"


def test_cli_missing_config_returns_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = cli.main(["--config", str(tmp_path / "missing.yaml"), "--profile", "openai"])

    captured = capsys.readouterr()
    assert result == 1
    assert "配置文件不存在" in captured.err


def test_cli_missing_profile_returns_error_without_api_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = write_config(tmp_path / "mewcode.yaml")

    result = cli.main(["--config", str(config_path), "--profile", "missing"])

    captured = capsys.readouterr()
    assert result == 1
    assert "未找到名为 'missing' 的配置" in captured.err
    assert "sk-cli-secret" not in captured.err


def test_cli_requires_profile(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli.main([])

    captured = capsys.readouterr()
    assert result != 0
    assert "--profile" in captured.err


def test_main_signature_accepts_sequence() -> None:
    argv: Sequence[str] = ["--help"]

    result = cli.main(argv)

    assert result == 0
