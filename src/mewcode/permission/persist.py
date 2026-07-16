from __future__ import annotations

from typing import TYPE_CHECKING

from mewcode.llm import ToolCall

from .rule import Rule
from .settings import extract_target, friendly_name, load_settings, save_settings

if TYPE_CHECKING:
    from .engine import Engine


def allow_session(engine: Engine, call: ToolCall) -> None:
    engine.session.add_allow(rule_for(engine, call))


def persist_local_allow(engine: Engine, call: ToolCall) -> None:
    rule = rule_for(engine, call)
    settings = load_settings(engine.local_path)
    rendered = rule.render()
    if rendered not in settings.permissions.allow:
        settings.permissions.allow.append(rendered)
        save_settings(engine.local_path, settings)
    engine.local.add_allow(rule)


def rule_for(engine: Engine, call: ToolCall) -> Rule:
    target, is_file, ok = extract_target(call)
    if not ok:
        raise ValueError("无法生成参数不完整调用的权限规则")
    if is_file:
        resolved = engine.resolve_file_target(target)
        target = resolved.relative_to(engine.root).as_posix()
    return Rule(friendly_name(call.name), target, allow=True)
