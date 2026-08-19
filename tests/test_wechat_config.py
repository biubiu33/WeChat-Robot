from __future__ import annotations

import pytest

from mewcode.config import ConfigError, _from_dict
from mewcode.wechat.config import DEFAULT_SYSTEM_PROMPT, parse_wechat_config


def provider() -> dict[str, object]:
    return {
        "name": "chat",
        "protocol": "openai",
        "api_key": "secret",
        "model": "demo",
    }


def test_top_level_config_keeps_optional_wechat_mapping() -> None:
    config = _from_dict({"providers": [provider()], "wechat": {"enabled": False}})

    assert config.wechat == {"enabled": False}
    assert config.enable_subagent_background is True


def test_top_level_config_without_wechat_stays_compatible() -> None:
    assert _from_dict({"providers": [provider()]}).wechat is None


def test_top_level_wechat_must_be_mapping() -> None:
    with pytest.raises(ConfigError, match="wechat 必须是对象"):
        _from_dict({"providers": [provider()], "wechat": []})


def test_parse_enabled_wechat_config() -> None:
    config = parse_wechat_config(
        {
            "enabled": True,
            "provider": "chat",
            "allowed_contacts": ["文件传输助手"],
        },
        {"chat"},
    )

    assert config.allowed_contacts == ("文件传输助手",)
    assert config.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert config.task_timeout_seconds == 180
    assert config.max_reply_chars == 1500


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("enabled", "yes", "enabled 必须是布尔值"),
        ("allowed_contacts", "friend", "必须是字符串列表"),
        ("task_timeout_seconds", 0, "必须是正数"),
        ("max_reply_chars", True, "必须是正整数"),
        ("log_level", "TRACE", "log_level 必须是"),
    ],
)
def test_parse_wechat_config_rejects_invalid_values(
    field: str, value: object, message: str
) -> None:
    raw = {
        "enabled": True,
        "provider": "chat",
        "allowed_contacts": ["文件传输助手"],
        field: value,
    }
    with pytest.raises(ConfigError, match=message):
        parse_wechat_config(raw, {"chat"})


def test_enabled_config_requires_known_provider_and_allowlist() -> None:
    with pytest.raises(ConfigError, match="未引用现有 Provider"):
        parse_wechat_config(
            {"enabled": True, "provider": "missing", "allowed_contacts": ["A"]},
            {"chat"},
        )
    with pytest.raises(ConfigError, match="allowed_contacts 不能为空"):
        parse_wechat_config(
            {"enabled": True, "provider": "chat", "allowed_contacts": []},
            {"chat"},
        )
