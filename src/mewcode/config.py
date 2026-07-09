from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


ProtocolName = Literal["anthropic", "openai"]
CONFIG_ENV_VAR = "MEWCODE_CONFIG"
CONFIG_RELATIVE_PATH = Path(".mewcode") / "config.yaml"


class ConfigError(Exception):
    """Raised when the local MewCode configuration is missing or invalid."""


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    protocol: ProtocolName
    api_key: str
    model: str
    base_url: str | None = None
    thinking: bool = False


@dataclass(frozen=True)
class Config:
    providers: list[ProviderConfig] = field(default_factory=list)


@dataclass(frozen=True)
class ConfigDiscoveryResult:
    path: Path
    attempted_paths: list[Path]


def discover_config_path(
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    home: Path | None = None,
) -> ConfigDiscoveryResult:
    config_env = os.environ if env is None else env
    current_dir = Path.cwd() if cwd is None else cwd
    home_dir = Path.home() if home is None else home

    env_path = config_env.get(CONFIG_ENV_VAR, "").strip()
    if env_path:
        attempted_paths = [Path(env_path).expanduser()]
    else:
        attempted_paths = [
            current_dir / CONFIG_RELATIVE_PATH,
            home_dir / CONFIG_RELATIVE_PATH,
        ]

    for path in attempted_paths:
        if path.is_file():
            return ConfigDiscoveryResult(path=path, attempted_paths=attempted_paths)

    attempted = "\n".join(f"- {path}" for path in attempted_paths)
    raise ConfigError(f"未找到配置文件，已尝试以下位置:\n{attempted}")


def load(path: str) -> Config:
    config_path = Path(path)
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件: {path}: {exc}") from exc

    try:
        import yaml

        raw = yaml.safe_load(raw_text)
    except ImportError as exc:
        raise ConfigError("缺少依赖 pyyaml，请先安装项目依赖") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件 YAML 格式错误: {path}: {exc}") from exc

    return _from_dict(raw)


def _from_dict(raw: Any) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("配置文件顶层必须是对象，并包含 providers 列表")

    providers_raw = raw.get("providers")
    if not isinstance(providers_raw, list) or not providers_raw:
        raise ConfigError("providers 必须是非空列表")

    providers: list[ProviderConfig] = []
    seen_names: set[str] = set()
    for index, item in enumerate(providers_raw):
        if not isinstance(item, dict):
            raise ConfigError(f"providers[{index}] 必须是对象")

        name = _required_str(item, index, "name")
        protocol = _required_str(item, index, "protocol")
        api_key = _required_str(item, index, "api_key")
        model = _required_str(item, index, "model")

        if protocol not in ("anthropic", "openai"):
            raise ConfigError(f"providers[{index}].protocol 必须是 anthropic 或 openai")
        if name in seen_names:
            raise ConfigError(f"providers[{index}].name 重复: {name}")
        seen_names.add(name)

        base_url = item.get("base_url")
        if base_url is not None and (not isinstance(base_url, str) or not base_url.strip()):
            raise ConfigError(f"providers[{index}].base_url 必须是非空字符串或省略")

        thinking = item.get("thinking", False)
        if not isinstance(thinking, bool):
            raise ConfigError(f"providers[{index}].thinking 必须是布尔值")

        providers.append(
            ProviderConfig(
                name=name,
                protocol=protocol,
                api_key=api_key,
                model=model,
                base_url=base_url.strip() if isinstance(base_url, str) else None,
                thinking=thinking,
            )
        )

    return Config(providers=providers)


def _required_str(item: dict[str, Any], index: int, field_name: str) -> str:
    value = item.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"providers[{index}].{field_name} 不能为空")
    return value.strip()
