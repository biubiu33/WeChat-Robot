from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mewcode.llm import ToolCall

from . import Category
from .rule import RuleSet, parse_rule_detail


@dataclass
class PermissionsBlock:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class Settings:
    default_mode: str = ""
    permissions: PermissionsBlock = field(default_factory=PermissionsBlock)


_FRIENDLY_NAMES = {
    "bash": "Bash",
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "glob": "Glob",
    "grep": "Grep",
}
_FILE_TOOLS = {"read_file", "write_file", "edit_file", "glob", "grep"}
_READ_TOOLS = {"read_file", "glob", "grep"}


def load_settings(path: Path) -> Settings:
    """读取单个权限文件；任何失败均降级为空配置。"""

    try:
        raw_text = path.read_text(encoding="utf-8")
        import yaml

        raw = yaml.safe_load(raw_text)
    except (ImportError, OSError, ValueError):
        return Settings()
    except Exception:
        return Settings()
    if not isinstance(raw, dict):
        return Settings()

    default_mode = raw.get("default_mode", "")
    if not isinstance(default_mode, str):
        default_mode = ""
    permissions_raw = raw.get("permissions", {})
    if not isinstance(permissions_raw, dict):
        permissions_raw = {}
    allow = _strings(permissions_raw.get("allow"))
    deny = _strings(permissions_raw.get("deny"))
    return Settings(
        default_mode=default_mode, permissions=PermissionsBlock(allow, deny)
    )


def save_settings(path: Path, settings: Settings) -> None:
    """将本地权限配置以 UTF-8 YAML 写回磁盘。"""

    import yaml

    payload: dict[str, Any] = {
        "permissions": {
            "allow": settings.permissions.allow,
            "deny": settings.permissions.deny,
        }
    }
    if settings.default_mode:
        payload = {"default_mode": settings.default_mode, **payload}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def to_rule_set(settings: Settings) -> RuleSet:
    rule_set = RuleSet()
    for text in settings.permissions.allow:
        rule, reason = parse_rule_detail(text, allow=True)
        if rule is not None:
            rule_set.allow.append(rule)
        else:
            print(f'[permission] rule "{text}" parse failed: {reason}', file=sys.stderr)
    for text in settings.permissions.deny:
        rule, reason = parse_rule_detail(text, allow=False)
        if rule is not None:
            rule_set.deny.append(rule)
        else:
            print(f'[permission] rule "{text}" parse failed: {reason}', file=sys.stderr)
    return rule_set


def friendly_name(internal: str) -> str:
    return _FRIENDLY_NAMES.get(internal, internal)


def categorize(internal: str, read_only: bool) -> Category:
    if read_only or internal in _READ_TOOLS:
        return Category.READ
    if internal in {"write_file", "edit_file"}:
        return Category.WRITE
    return Category.EXEC


def extract_target(call: ToolCall) -> tuple[str, bool, bool]:
    """返回 target、是否文件类、参数是否可安全解析。"""

    file_tool = call.name in _FILE_TOOLS
    try:
        values = json.loads(call.input or "{}")
    except (TypeError, json.JSONDecodeError):
        return "", file_tool, False
    if not isinstance(values, dict):
        return "", file_tool, False

    if call.name in {"read_file", "write_file", "edit_file"}:
        path = values.get("path")
        return (
            (path, True, bool(isinstance(path, str) and path))
            if isinstance(path, str)
            else ("", True, False)
        )
    if call.name in {"glob", "grep"}:
        path = values.get("path", ".")
        return (
            (path, True, bool(isinstance(path, str) and path))
            if isinstance(path, str)
            else ("", True, False)
        )
    if call.name == "bash":
        command = values.get("command")
        return (
            (command, False, bool(command))
            if isinstance(command, str)
            else ("", False, False)
        )
    return "", False, False


def _strings(value: object) -> list[str]:
    return (
        [item for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )
