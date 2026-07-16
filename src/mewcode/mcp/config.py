"""User-level MCP server configuration loading and validation."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

MCP_CONFIG_RELATIVE_PATH = Path(".mewcode") / "mcp.yaml"
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class ServerConfig:
    type: Literal["stdio", "http"]
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    servers: dict[str, ServerConfig] = field(default_factory=dict)


def load_config(home: Path | None = None) -> Config:
    """Load MCP servers from ~/.mewcode/mcp.yaml without blocking startup."""

    home_dir = Path.home() if home is None else home
    raw_servers = _load_file(home_dir / MCP_CONFIG_RELATIVE_PATH)
    servers: dict[str, ServerConfig] = {}
    for name, raw_server in raw_servers.items():
        expanded = _apply_expansion(name, raw_server)
        validated = _validate_server(name, expanded)
        if validated is not None:
            servers[name] = validated
    return Config(servers=servers)


def _load_file(path: Path) -> dict[str, dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        _warn(f"cannot read MCP config {path}: {exc}")
        return {}

    try:
        import yaml

        raw = yaml.safe_load(text)
    except Exception:
        _warn(f"cannot parse MCP config {path}")
        return {}

    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _warn("MCP config root must be a map")
        return {}
    servers = raw.get("mcp_servers")
    if servers is None:
        return {}
    if not isinstance(servers, dict):
        _warn("mcp_servers must be a map")
        return {}

    result: dict[str, dict[str, Any]] = {}
    for name, value in servers.items():
        if not isinstance(name, str) or not name:
            _warn("skip MCP server with an invalid name")
            continue
        if not isinstance(value, dict):
            _warn(f"skip server {name}: definition must be a map")
            continue
        result[name] = dict(value)
    return result


def _apply_expansion(name: str, raw_server: dict[str, Any]) -> dict[str, Any]:
    result = dict(raw_server)
    warned: set[str] = set()
    for field_name in ("env", "headers"):
        values = result.get(field_name)
        if not isinstance(values, dict):
            continue
        expanded: dict[Any, Any] = {}
        for key, value in values.items():
            if isinstance(value, str):
                expanded_value, undefined = _expand_vars(value)
                for var_name in undefined:
                    if var_name not in warned:
                        _warn(
                            f"undefined env var ${{{var_name}}} referenced by server {name}"
                        )
                        warned.add(var_name)
                expanded[key] = expanded_value
            else:
                expanded[key] = value
        result[field_name] = expanded
    return result


def _expand_vars(value: str) -> tuple[str, set[str]]:
    undefined: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        env_value = os.environ.get(name)
        if env_value is None:
            undefined.add(name)
            return ""
        return env_value

    return _ENV_VAR_PATTERN.sub(replace, value), undefined


def _validate_server(name: str, raw: dict[str, Any]) -> ServerConfig | None:
    server_type = raw.get("type")
    if server_type not in ("stdio", "http"):
        _skip(name, "type must be stdio or http")
        return None

    command = raw.get("command", "")
    url = raw.get("url", "")
    args = raw.get("args", [])
    env = raw.get("env", {})
    headers = raw.get("headers", {})
    if not isinstance(command, str) or not isinstance(url, str):
        _skip(name, "command and url must be strings")
        return None
    if not _is_string_list(args):
        _skip(name, "args must be a list of strings")
        return None
    if not _is_string_map(env) or not _is_string_map(headers):
        _skip(name, "env and headers must be maps of strings")
        return None
    if server_type == "stdio" and not command.strip():
        _skip(name, "stdio server requires command")
        return None
    if server_type == "http" and not url.strip():
        _skip(name, "http server requires url")
        return None
    return ServerConfig(
        type=server_type,
        command=command,
        args=list(args),
        env=dict(env),
        url=url,
        headers=dict(headers),
    )


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_string_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    )


def _skip(name: str, reason: str) -> None:
    _warn(f"skip server {name}: {reason}")


def _warn(message: str) -> None:
    print(f"[mcp] warn: {message}", file=sys.stderr)
