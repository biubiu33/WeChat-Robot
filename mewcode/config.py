from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence, cast

import yaml

from mewcode.errors import ConfigError
from mewcode.models import ProviderProfile, ProviderProtocol
from mewcode.providers.base import redact_secret

REQUIRED_PROFILE_FIELDS = {"name", "protocol", "model", "base_url", "api_key"}
SUPPORTED_PROTOCOLS = {"openai", "anthropic"}


def load_profiles(path: Path) -> list[ProviderProfile]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在：{path}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件：{path}，原因：{exc}") from exc

    try:
        raw_config = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件不是有效的 YAML：{exc}") from exc

    if not isinstance(raw_config, dict):
        raise ConfigError("配置文件格式无效：顶层必须是对象，并包含 providers 列表。")

    providers = raw_config.get("providers")
    if not isinstance(providers, list):
        raise ConfigError("配置文件格式无效：providers 必须是列表。")

    profiles: list[ProviderProfile] = []
    seen_names: set[str] = set()
    for index, item in enumerate(providers, start=1):
        profile = _parse_profile(item, index)
        if profile.name in seen_names:
            raise ConfigError(f"配置文件格式无效：profile 名称重复：{profile.name}")
        seen_names.add(profile.name)
        profiles.append(profile)

    if not profiles:
        raise ConfigError("配置文件格式无效：providers 至少需要包含一个配置。")

    return profiles


def select_profile(profiles: Sequence[ProviderProfile], name: str) -> ProviderProfile:
    for profile in profiles:
        if profile.name == name:
            return profile
    available = "、".join(profile.name for profile in profiles) or "无"
    raise ConfigError(f"未找到名为 {name!r} 的配置。可用配置：{available}")


def _parse_profile(raw_profile: Any, index: int) -> ProviderProfile:
    if not isinstance(raw_profile, dict):
        raise ConfigError(f"配置文件格式无效：第 {index} 个 provider 必须是对象。")

    missing = sorted(REQUIRED_PROFILE_FIELDS - raw_profile.keys())
    if missing:
        raise ConfigError(
            f"配置文件格式无效：第 {index} 个 provider 缺少字段：{', '.join(missing)}"
        )

    name = _require_non_empty_string(raw_profile, "name", index)
    protocol_value = _require_non_empty_string(raw_profile, "protocol", index)
    if protocol_value not in SUPPORTED_PROTOCOLS:
        raise ConfigError(
            f"配置文件格式无效：profile {name!r} 的 protocol 必须是 openai 或 anthropic。"
        )

    model = _require_non_empty_string(raw_profile, "model", index)
    base_url = _require_non_empty_string(raw_profile, "base_url", index).rstrip("/")
    api_key = _require_non_empty_string(raw_profile, "api_key", index)
    thinking = raw_profile.get("thinking", False)
    if not isinstance(thinking, bool):
        raise ConfigError(
            redact_secret(
                f"配置文件格式无效：profile {name!r} 的 thinking 必须是布尔值。",
                api_key,
            )
        )

    return ProviderProfile(
        name=name,
        protocol=cast(ProviderProtocol, protocol_value),
        model=model,
        base_url=base_url,
        api_key=api_key,
        thinking=thinking,
    )


def _require_non_empty_string(raw_profile: dict[str, Any], field: str, index: int) -> str:
    value = raw_profile.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"配置文件格式无效：第 {index} 个 provider 的 {field} 必须是非空字符串。"
        )
    return value.strip()
