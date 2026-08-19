from __future__ import annotations

import os
import re
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from mewcode.config import ConfigError


DEFAULT_SYSTEM_PROMPT = (
    "你是通过微信与好友聊天的个人助手。简洁、自然地回答；"
    "你没有任何本地工具，不能执行命令、读写文件或操作电脑。"
)
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
ENV_REFERENCE_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


@dataclass(frozen=True)
class WechatInfoConfig:
    enabled: bool = False
    tavily_api_key: str = field(default="", repr=False)
    nominatim_user_agent: str = "MewCode-WeChat/0.1"
    nominatim_proxy: str = field(default="", repr=False)
    nominatim_proxy_configured: bool = False


@dataclass(frozen=True)
class WechatConfig:
    enabled: bool
    provider: str
    allowed_contacts: tuple[str, ...]
    system_prompt: str
    task_timeout_seconds: float
    max_reply_chars: int
    log_level: str
    info_tools: WechatInfoConfig = field(default_factory=WechatInfoConfig)


def parse_wechat_config(
    raw: object, provider_names: set[str] | frozenset[str]
) -> WechatConfig:
    if not isinstance(raw, dict):
        raise ConfigError("wechat 必须是对象")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("wechat.enabled 必须是布尔值")

    provider = _optional_str(raw, "provider", "")
    contacts_raw = raw.get("allowed_contacts", [])
    if not isinstance(contacts_raw, list):
        raise ConfigError("wechat.allowed_contacts 必须是字符串列表")
    contacts: list[str] = []
    for index, value in enumerate(contacts_raw):
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"wechat.allowed_contacts[{index}] 必须是非空字符串")
        contact = value.strip()
        if contact in contacts:
            raise ConfigError(f"wechat.allowed_contacts 存在重复项: {contact}")
        contacts.append(contact)

    system_prompt = _optional_str(raw, "system_prompt", DEFAULT_SYSTEM_PROMPT)
    timeout = _positive_number(raw, "task_timeout_seconds", 180.0)
    max_reply_chars = _positive_int(raw, "max_reply_chars", 1500)
    log_level = _optional_str(raw, "log_level", "INFO").upper()
    if log_level not in LOG_LEVELS:
        raise ConfigError(
            "wechat.log_level 必须是 DEBUG、INFO、WARNING、ERROR 或 CRITICAL"
        )
    info_tools = _parse_info_tools(raw.get("info_tools", {}))

    if enabled:
        if not provider:
            raise ConfigError("启用微信机器人时必须配置 wechat.provider")
        if provider not in provider_names:
            raise ConfigError(f"wechat.provider 未引用现有 Provider: {provider}")
        if not contacts:
            raise ConfigError("启用微信机器人时 allowed_contacts 不能为空")

    return WechatConfig(
        enabled=enabled,
        provider=provider,
        allowed_contacts=tuple(contacts),
        system_prompt=system_prompt,
        task_timeout_seconds=timeout,
        max_reply_chars=max_reply_chars,
        log_level=log_level,
        info_tools=info_tools,
    )


def _parse_info_tools(raw: object) -> WechatInfoConfig:
    if not isinstance(raw, dict):
        raise ConfigError("wechat.info_tools 必须是对象")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("wechat.info_tools.enabled 必须是布尔值")

    api_key = raw.get("tavily_api_key", "")
    if not isinstance(api_key, str):
        raise ConfigError("wechat.info_tools.tavily_api_key 必须是字符串")
    api_key = api_key.strip()
    match = ENV_REFERENCE_RE.fullmatch(api_key)
    if match is not None:
        api_key = os.environ.get(match.group(1), "").strip()

    user_agent = raw.get("nominatim_user_agent", "MewCode-WeChat/0.1")
    if not isinstance(user_agent, str) or not user_agent.strip():
        raise ConfigError("wechat.info_tools.nominatim_user_agent 必须是非空字符串")

    proxy_configured = "nominatim_proxy" in raw
    proxy = raw.get("nominatim_proxy", "")
    if not isinstance(proxy, str):
        raise ConfigError("wechat.info_tools.nominatim_proxy 必须是字符串")
    proxy = proxy.strip()
    match = ENV_REFERENCE_RE.fullmatch(proxy)
    if match is not None:
        proxy = os.environ.get(match.group(1), "").strip()

    return WechatInfoConfig(
        enabled=enabled,
        tavily_api_key=api_key,
        nominatim_user_agent=user_agent.strip(),
        nominatim_proxy=proxy,
        nominatim_proxy_configured=proxy_configured,
    )


def _optional_str(raw: dict[str, Any], key: str, default: str) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str) or (key == "system_prompt" and not value.strip()):
        raise ConfigError(f"wechat.{key} 必须是非空字符串")
    return value.strip()


def _positive_number(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"wechat.{key} 必须是正数")
    return float(value)


def _positive_int(raw: dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"wechat.{key} 必须是正整数")
    return value


__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "WechatConfig",
    "WechatInfoConfig",
    "parse_wechat_config",
]
