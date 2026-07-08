from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.config import load_profiles, select_profile
from mewcode.errors import ConfigError


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_multiple_profiles(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "mewcode.yaml",
        """
providers:
  - name: openai
    protocol: openai
    model: gpt-test
    base_url: https://example.test/v1/
    api_key: sk-openai-secret
  - name: claude
    protocol: anthropic
    model: claude-test
    base_url: https://anthropic.test/v1
    api_key: sk-ant-secret
    thinking: true
""",
    )

    profiles = load_profiles(config_path)

    assert [profile.name for profile in profiles] == ["openai", "claude"]
    assert profiles[0].thinking is False
    assert profiles[0].base_url == "https://example.test/v1"
    assert profiles[1].thinking is True


def test_select_profile_by_name(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "mewcode.yaml",
        """
providers:
  - name: claude
    protocol: anthropic
    model: claude-test
    base_url: https://anthropic.test/v1
    api_key: sk-ant-secret
""",
    )

    profile = select_profile(load_profiles(config_path), "claude")

    assert profile.protocol == "anthropic"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("{}", "providers 必须是列表"),
        ("providers: []", "至少需要包含一个配置"),
        (
            """
providers:
  - name: broken
    protocol: openai
    model: gpt-test
    base_url: https://example.test/v1
""",
            "缺少字段：api_key",
        ),
        (
            """
providers:
  - name: one
    protocol: openai
    model: gpt-test
    base_url: https://example.test/v1
    api_key: sk-one
  - name: one
    protocol: anthropic
    model: claude-test
    base_url: https://anthropic.test/v1
    api_key: sk-two
""",
            "profile 名称重复：one",
        ),
        (
            """
providers:
  - name: bad
    protocol: other
    model: gpt-test
    base_url: https://example.test/v1
    api_key: sk-secret
""",
            "protocol 必须是 openai 或 anthropic",
        ),
    ],
)
def test_invalid_config_reports_chinese_error(
    tmp_path: Path, body: str, expected: str
) -> None:
    config_path = write_config(tmp_path / "mewcode.yaml", body)

    with pytest.raises(ConfigError) as exc_info:
        load_profiles(config_path)

    assert expected in str(exc_info.value)


def test_missing_profile_reports_available_names(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "mewcode.yaml",
        """
providers:
  - name: openai
    protocol: openai
    model: gpt-test
    base_url: https://example.test/v1
    api_key: sk-secret
""",
    )

    with pytest.raises(ConfigError) as exc_info:
        select_profile(load_profiles(config_path), "claude")

    message = str(exc_info.value)
    assert "未找到名为 'claude' 的配置" in message
    assert "openai" in message


def test_api_key_is_not_leaked_in_config_error(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path / "mewcode.yaml",
        """
providers:
  - name: openai
    protocol: openai
    model: gpt-test
    base_url: https://example.test/v1
    api_key: sk-very-secret
    thinking: "yes"
""",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_profiles(config_path)

    assert "sk-very-secret" not in str(exc_info.value)


def test_missing_file_reports_chinese_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as exc_info:
        load_profiles(tmp_path / "missing.yaml")

    assert "配置文件不存在" in str(exc_info.value)
