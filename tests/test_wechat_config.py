from __future__ import annotations

from dataclasses import fields

import pytest

from mewcode.config import ConfigError, _from_dict
from mewcode.wechat.config import WechatInfoConfig, parse_wechat_config


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
    assert "system_prompt" not in {field.name for field in fields(config)}
    assert config.task_timeout_seconds == 180
    assert config.max_reply_chars == 1500


def test_legacy_system_prompt_is_ignored() -> None:
    config = parse_wechat_config(
        {
            "enabled": True,
            "provider": "chat",
            "allowed_contacts": ["好友"],
            "system_prompt": "自定义角色",
        },
        {"chat"},
    )

    assert "system_prompt" not in {field.name for field in fields(config)}


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


def test_info_tools_default_off_and_expand_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        parse_wechat_config({"enabled": False}, {"chat"}).info_tools
        == WechatInfoConfig()
    )

    monkeypatch.setenv("TAVILY_TEST_KEY", "private-key")
    config = parse_wechat_config(
        {
            "enabled": False,
            "info_tools": {
                "enabled": True,
                "tavily_api_key": "${TAVILY_TEST_KEY}",
                "nominatim_user_agent": "MewCode-Test/1.0",
            },
        },
        {"chat"},
    )
    assert config.info_tools == WechatInfoConfig(
        True, "private-key", "MewCode-Test/1.0"
    )

    monkeypatch.delenv("TAVILY_TEST_KEY")
    missing = parse_wechat_config(
        {"enabled": False, "info_tools": {"tavily_api_key": "${TAVILY_TEST_KEY}"}},
        {"chat"},
    )
    assert missing.info_tools.tavily_api_key == ""


def test_nominatim_proxy_tracks_presence_and_expands_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    omitted = parse_wechat_config({"enabled": False}, {"chat"}).info_tools
    assert omitted.nominatim_proxy == ""
    assert omitted.nominatim_proxy_configured is False

    literal = parse_wechat_config(
        {
            "enabled": False,
            "info_tools": {"nominatim_proxy": "http://proxy.example:8080"},
        },
        {"chat"},
    ).info_tools
    assert literal.nominatim_proxy == "http://proxy.example:8080"
    assert literal.nominatim_proxy_configured is True

    monkeypatch.setenv("NOMINATIM_TEST_PROXY", "https://proxy.example:8443")
    expanded = parse_wechat_config(
        {
            "enabled": False,
            "info_tools": {"nominatim_proxy": "${NOMINATIM_TEST_PROXY}"},
        },
        {"chat"},
    ).info_tools
    assert expanded.nominatim_proxy == "https://proxy.example:8443"
    assert expanded.nominatim_proxy_configured is True

    monkeypatch.delenv("NOMINATIM_TEST_PROXY")
    missing = parse_wechat_config(
        {
            "enabled": False,
            "info_tools": {"nominatim_proxy": "${NOMINATIM_TEST_PROXY}"},
        },
        {"chat"},
    ).info_tools
    assert missing.nominatim_proxy == ""
    assert missing.nominatim_proxy_configured is True


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"info_tools": []}, "info_tools 必须是对象"),
        ({"info_tools": {"enabled": 1}}, "info_tools.enabled 必须是布尔值"),
        ({"info_tools": {"tavily_api_key": 1}}, "tavily_api_key 必须是字符串"),
        ({"info_tools": {"nominatim_user_agent": ""}}, "user_agent 必须是非空字符串"),
        ({"info_tools": {"nominatim_proxy": 1}}, "nominatim_proxy 必须是字符串"),
    ],
)
def test_info_tools_reject_invalid_config(raw: object, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_wechat_config(raw, {"chat"})
