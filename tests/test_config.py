from __future__ import annotations

from pathlib import Path

import pytest

import mewcode.cli as cli
from mewcode.config import ConfigError, discover_config_path, load
from mewcode.config import Config, ConfigDiscoveryResult, ProviderConfig
from mewcode.mcp import Config as McpConfig


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_valid_config(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
providers:
  - name: claude
    protocol: anthropic
    api_key: sk-ant-secret
    model: claude-3-5-sonnet-latest
    thinking: true
    context_window: 200000
  - name: openai
    protocol: openai
    api_key: sk-secret
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1
""",
    )

    cfg = load(str(path))

    assert len(cfg.providers) == 2
    assert cfg.providers[0].name == "claude"
    assert cfg.providers[0].thinking is True
    assert cfg.providers[0].context_window == 200000
    assert cfg.providers[1].base_url == "https://api.openai.com/v1"
    assert cfg.providers[1].context_window == 1_000_000


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("providers: []\n", "providers 必须是非空列表"),
        (
            """
providers:
  - name: bad
    protocol: unknown
    api_key: sk-secret
    model: demo
""",
            "protocol 必须是 anthropic 或 openai",
        ),
        (
            """
providers:
  - name: bad
    protocol: openai
    model: demo
""",
            "api_key 不能为空",
        ),
        (
            """
providers:
  - name: bad
    protocol: openai
    api_key: sk-secret
    model: demo
    context_window: 0
""",
            "context_window 必须是正整数",
        ),
    ],
)
def test_invalid_config_raises_readable_error(
    tmp_path: Path, body: str, message: str
) -> None:
    path = write_config(tmp_path, body)

    with pytest.raises(ConfigError, match=message):
        load(str(path))


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="配置文件不存在"):
        load(str(tmp_path / "missing.yaml"))


def test_discover_config_uses_only_home_config(tmp_path: Path) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    (home / ".mewcode").mkdir(parents=True)
    (project / ".mewcode").mkdir(parents=True)
    (project / ".mewcode" / "config.yaml").write_text(
        "providers: []\n", encoding="utf-8"
    )
    (home / ".mewcode" / "config.yaml").write_text("providers: []\n", encoding="utf-8")

    result = discover_config_path(home=home)

    assert result.path == home / ".mewcode" / "config.yaml"
    assert result.attempted_paths == [home / ".mewcode" / "config.yaml"]


def test_discover_config_does_not_support_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = write_config(tmp_path, "providers: []\n")
    home = tmp_path / "home"
    home_config = home / ".mewcode" / "config.yaml"
    home_config.parent.mkdir(parents=True)
    home_config.write_text("providers: []\n", encoding="utf-8")
    monkeypatch.setenv("MEWCODE_CONFIG", str(override))

    result = discover_config_path(home=home)

    assert result.path == home_config


def test_discover_config_lists_only_home_path_when_missing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    home_config = home / ".mewcode" / "config.yaml"

    with pytest.raises(ConfigError) as exc_info:
        discover_config_path(home=home)

    message = str(exc_info.value)
    assert "未找到配置文件" in message
    assert str(home_config) in message


def test_cli_constructs_engine_from_startup_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    provider = ProviderConfig(
        name="test", protocol="openai", api_key="test-key", model="test-model"
    )
    captured: dict[str, object] = {}

    class FakeApp:
        def __init__(self, *args: object, **kwargs: object) -> None:
            captured["args"] = args
            captured["kwargs"] = kwargs

        async def run_async(self) -> None:
            captured["ran"] = True

    class FakeManager:
        def tools(self) -> list[object]:
            return []

        async def close(self) -> None:
            captured["closed"] = True

    async def fake_new_manager(*args: object, **kwargs: object) -> FakeManager:
        return FakeManager()

    import mewcode.tui.app as tui_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "discover_config_path",
        lambda: ConfigDiscoveryResult(config_path, [config_path]),
    )
    monkeypatch.setattr(cli, "load", lambda path: Config([provider]))
    monkeypatch.setattr(cli, "load_mcp_config", lambda: McpConfig())
    monkeypatch.setattr(cli, "new_manager", fake_new_manager)
    monkeypatch.setattr(tui_app, "MewCodeApp", FakeApp)

    cli.main()

    engine = captured["kwargs"]["engine"]  # type: ignore[index]
    assert engine.root == tmp_path.resolve()
    assert captured["ran"] is True
    assert captured["closed"] is True
