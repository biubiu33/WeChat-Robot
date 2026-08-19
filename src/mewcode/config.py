from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


ProtocolName = Literal["anthropic", "openai"]
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
    context_window: int = 1_000_000


@dataclass(frozen=True)
class Config:
    providers: list[ProviderConfig] = field(default_factory=list)
    enable_subagent_background: bool = True
    wechat: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConfigDiscoveryResult:
    path: Path
    attempted_paths: list[Path]


def discover_config_path(
    home: Path | None = None,
) -> ConfigDiscoveryResult:
    home_dir = Path.home() if home is None else home
    path = home_dir / CONFIG_RELATIVE_PATH
    if path.is_file():
        return ConfigDiscoveryResult(path=path, attempted_paths=[path])
    raise ConfigError(f"未找到配置文件，已尝试以下位置:\n- {path}")


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
        if base_url is not None and (
            not isinstance(base_url, str) or not base_url.strip()
        ):
            raise ConfigError(f"providers[{index}].base_url 必须是非空字符串或省略")

        thinking = item.get("thinking", False)
        if not isinstance(thinking, bool):
            raise ConfigError(f"providers[{index}].thinking 必须是布尔值")

        context_window = item.get("context_window", 1_000_000)
        if (
            isinstance(context_window, bool)
            or not isinstance(context_window, int)
            or context_window <= 0
        ):
            raise ConfigError(f"providers[{index}].context_window 必须是正整数或省略")

        providers.append(
            ProviderConfig(
                name=name,
                protocol=protocol,
                api_key=api_key,
                model=model,
                base_url=base_url.strip() if isinstance(base_url, str) else None,
                thinking=thinking,
                context_window=context_window,
            )
        )

    enable_subagent_background = raw.get("enable_subagent_background", True)
    if not isinstance(enable_subagent_background, bool):
        raise ConfigError("enable_subagent_background 必须是布尔值")
    wechat = raw.get("wechat")
    if wechat is not None and not isinstance(wechat, dict):
        raise ConfigError("wechat 必须是对象或省略")
    return Config(
        providers=providers,
        enable_subagent_background=enable_subagent_background,
        wechat=dict(wechat) if wechat is not None else None,
    )


def _required_str(item: dict[str, Any], index: int, field_name: str) -> str:
    value = item.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"providers[{index}].{field_name} 不能为空")
    return value.strip()
