from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.config import ConfigError, discover_config_path, load


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
    assert cfg.providers[1].base_url == "https://api.openai.com/v1"


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
    ],
)
def test_invalid_config_raises_readable_error(tmp_path: Path, body: str, message: str) -> None:
    path = write_config(tmp_path, body)

    with pytest.raises(ConfigError, match=message):
        load(str(path))


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="配置文件不存在"):
        load(str(tmp_path / "missing.yaml"))


def test_discover_config_uses_env_path_first(tmp_path: Path) -> None:
    env_config = write_config(tmp_path, "providers: []\n")
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    (cwd / ".mewcode").mkdir(parents=True)
    (home / ".mewcode").mkdir(parents=True)
    (cwd / ".mewcode" / "config.yaml").write_text("providers: []\n", encoding="utf-8")
    (home / ".mewcode" / "config.yaml").write_text("providers: []\n", encoding="utf-8")

    result = discover_config_path(
        env={"MEWCODE_CONFIG": str(env_config)},
        cwd=cwd,
        home=home,
    )

    assert result.path == env_config
    assert result.attempted_paths == [env_config]


def test_discover_config_prefers_cwd_over_home(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd_config = cwd / ".mewcode" / "config.yaml"
    home_config = home / ".mewcode" / "config.yaml"
    cwd_config.parent.mkdir(parents=True)
    home_config.parent.mkdir(parents=True)
    cwd_config.write_text("providers: []\n", encoding="utf-8")
    home_config.write_text("providers: []\n", encoding="utf-8")

    result = discover_config_path(env={}, cwd=cwd, home=home)

    assert result.path == cwd_config
    assert result.attempted_paths == [cwd_config, home_config]


def test_discover_config_falls_back_to_home(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home_config = home / ".mewcode" / "config.yaml"
    home_config.parent.mkdir(parents=True)
    home_config.write_text("providers: []\n", encoding="utf-8")

    result = discover_config_path(env={}, cwd=cwd, home=home)

    assert result.path == home_config


def test_discover_config_lists_attempted_paths_when_missing(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    cwd_config = cwd / ".mewcode" / "config.yaml"
    home_config = home / ".mewcode" / "config.yaml"

    with pytest.raises(ConfigError) as exc_info:
        discover_config_path(env={}, cwd=cwd, home=home)

    message = str(exc_info.value)
    assert "未找到配置文件" in message
    assert str(cwd_config) in message
    assert str(home_config) in message
