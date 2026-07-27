from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

from mewcode.permission.rule import Pattern

from .model import (
    BLOCKING_EVENTS,
    Action,
    Condition,
    ConditionGroup,
    Hook,
    HookCatalog,
    HookEvent,
)


_HOOK_KEYS = {"name", "event", "if", "action", "only_once", "async", "timeout"}
_ACTION_KEYS = {
    "shell": {"type", "command"},
    "prompt": {"type", "text"},
    "http": {"type", "url", "method", "headers", "body"},
    "subagent": {"type", "agent_name", "prompt"},
}
_DURATION = re.compile(r"^(\d+(?:\.\d+)?)(ms|s|m)$")


def load_catalog(root: Path, home: Path | None = None) -> HookCatalog:
    home_dir = Path.home() if home is None else home
    paths = (
        root / ".mewcode" / "hooks.yaml",
        home_dir / ".mewcode" / "hooks.yaml",
    )
    hooks: list[Hook] = []
    sources: list[Path] = []
    names: set[str] = set()
    for path in paths:
        parsed = _load_file(path)
        if parsed is None:
            continue
        sources.append(path)
        for index, raw_hook in enumerate(parsed):
            hook = _parse_hook(raw_hook, path, index)
            if hook is None:
                continue
            if hook.name in names:
                _warn(f'hook "{hook.name}": duplicate name, skipped')
                continue
            names.add(hook.name)
            hooks.append(hook)
    return HookCatalog(tuple(hooks), tuple(sources))


def _load_file(path: Path) -> list[Any] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        _warn(f"cannot read {path}: {exc}")
        return None
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        _warn(f"cannot parse {path}: {exc}")
        return None
    if not isinstance(raw, dict) or set(raw) != {"hooks"}:
        _warn(f"{path}: root must contain only hooks")
        return None
    hooks = raw.get("hooks")
    if not isinstance(hooks, list):
        _warn(f"{path}: hooks must be a list")
        return None
    return hooks


def _parse_hook(raw: Any, source: Path, index: int) -> Hook | None:
    prefix = f"{source}: hooks[{index}]"
    if not isinstance(raw, dict):
        _warn(f"{prefix}: hook must be a map, skipped")
        return None
    unknown = set(raw) - _HOOK_KEYS
    if unknown:
        _warn(f"{prefix}: unknown fields {', '.join(sorted(unknown))}, skipped")
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        _warn(f"{prefix}: name must be a non-empty string, skipped")
        return None
    event_raw = raw.get("event")
    try:
        event = HookEvent(event_raw)
    except (TypeError, ValueError):
        _warn(f'hook "{name}": unknown event "{event_raw}", skipped')
        return None
    action = _parse_action(raw.get("action"), name)
    if action is None:
        return None
    condition = _parse_condition(raw.get("if"), name)
    if raw.get("if") is not None and condition is None:
        return None
    only_once = raw.get("only_once", False)
    asynchronous = raw.get("async", False)
    if not isinstance(only_once, bool) or not isinstance(asynchronous, bool):
        _warn(f'hook "{name}": only_once and async must be booleans, skipped')
        return None
    timeout = _parse_timeout(raw.get("timeout", "30s"), name)
    if timeout is None:
        return None
    if asynchronous and event in BLOCKING_EVENTS:
        _warn(f'hook "{name}": async not allowed for blocking events, skipped')
        return None
    if asynchronous and action.type == "prompt":
        _warn(f'hook "{name}": async not allowed for prompt actions, skipped')
        return None
    return Hook(
        name=name.strip(),
        event=event,
        condition=condition,
        action=action,
        only_once=only_once,
        asynchronous=asynchronous,
        timeout_seconds=timeout,
        source=source,
    )


def _parse_action(raw: Any, name: str) -> Action | None:
    if not isinstance(raw, dict):
        _warn(f'hook "{name}": action must be a map, skipped')
        return None
    action_type = raw.get("type")
    if action_type not in _ACTION_KEYS:
        _warn(f'hook "{name}": unknown action type "{action_type}", skipped')
        return None
    unknown = set(raw) - _ACTION_KEYS[action_type]
    if unknown:
        fields = ", ".join(sorted(unknown))
        _warn(f'hook "{name}": unknown action fields {fields}, skipped')
        return None
    if action_type == "shell":
        command = raw.get("command")
        if not isinstance(command, str) or not command:
            _warn(f'hook "{name}": shell action requires command, skipped')
            return None
        return Action("shell", command=command)
    if action_type == "prompt":
        text = raw.get("text")
        if not isinstance(text, str) or not text:
            _warn(f'hook "{name}": prompt action requires text, skipped')
            return None
        return Action("prompt", text=text)
    if action_type == "subagent":
        agent_name = raw.get("agent_name")
        prompt = raw.get("prompt")
        if (
            not isinstance(agent_name, str)
            or not agent_name
            or not isinstance(prompt, str)
        ):
            _warn(f'hook "{name}": subagent requires agent_name and prompt, skipped')
            return None
        return Action("subagent", agent_name=agent_name, prompt=prompt)
    url = raw.get("url")
    method = raw.get("method", "POST")
    headers = raw.get("headers", {})
    body = raw.get("body")
    if not isinstance(url, str) or not url or not isinstance(method, str) or not method:
        _warn(f'hook "{name}": http action requires url and valid method, skipped')
        return None
    if not isinstance(headers, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in headers.items()
    ):
        _warn(f'hook "{name}": http headers must be a string map, skipped')
        return None
    if body is not None and not isinstance(body, str):
        _warn(f'hook "{name}": http body must be a string, skipped')
        return None
    return Action(
        "http", url=url, method=method.upper(), headers=dict(headers), body=body
    )


def _parse_condition(raw: Any, name: str) -> ConditionGroup | None:
    if not isinstance(raw, dict) or len(raw) != 1:
        _warn(f'hook "{name}": if must contain exactly one all_of or any_of, skipped')
        return None
    mode, entries = next(iter(raw.items()))
    if mode not in {"all_of", "any_of"} or not isinstance(entries, list):
        _warn(f'hook "{name}": if must contain an all_of or any_of list, skipped')
        return None
    conditions: list[Condition] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"field", "match"}:
            _warn(f'hook "{name}": invalid condition, skipped')
            return None
        field = entry.get("field")
        if not isinstance(field, str) or not field:
            _warn(f'hook "{name}": condition field must be a string, skipped')
            return None
        try:
            pattern = _parse_match(entry.get("match"))
        except ValueError as exc:
            _warn(f'hook "{name}": invalid match: {exc}, skipped')
            return None
        conditions.append(Condition(field, pattern))
    return ConditionGroup(mode, tuple(conditions))


def _parse_match(raw: Any) -> Pattern:
    if not isinstance(raw, dict):
        raise ValueError("match must be a map")
    match_type = raw.get("type")
    if match_type == "not":
        if set(raw) != {"type", "inner"}:
            raise ValueError("not requires only inner")
        return Pattern("not", inner=_parse_match(raw.get("inner")))
    if match_type not in {"exact", "glob", "regex"} or set(raw) != {"type", "value"}:
        raise ValueError("match type must be exact, glob, regex, or not")
    value = raw.get("value")
    if not isinstance(value, str):
        raise ValueError("match value must be a string")
    return Pattern(match_type, value)


def _parse_timeout(raw: Any, name: str) -> float | None:
    if not isinstance(raw, str):
        _warn(f'hook "{name}": timeout must be a duration string, skipped')
        return None
    match = _DURATION.fullmatch(raw)
    if match is None:
        _warn(f'hook "{name}": timeout must use ms, s, or m, skipped')
        return None
    amount = float(match.group(1))
    if amount <= 0:
        _warn(f'hook "{name}": timeout must be positive, skipped')
        return None
    unit = match.group(2)
    return amount / 1000 if unit == "ms" else amount * (60 if unit == "m" else 1)


def _warn(message: str) -> None:
    print(f"[hook] {message}", file=sys.stderr)
