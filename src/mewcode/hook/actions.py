from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

from .model import ActionResult, Hook, HookContext, HookSessionState


async def execute_action(
    hook: Hook,
    context: HookContext,
    state: HookSessionState,
    *,
    blocking: bool,
) -> ActionResult:
    action = hook.action
    if action.type == "prompt":
        state.reminders.append(action.text)
        return ActionResult(True)
    if action.type == "subagent":
        print(
            f"[hook subagent] not yet implemented, skipped: {hook.name}",
            file=sys.stderr,
        )
        return ActionResult(True)
    if action.type == "shell":
        return await _shell(hook, context, blocking=blocking)
    return await _http(hook, context, blocking=blocking)


async def _shell(hook: Hook, context: HookContext, *, blocking: bool) -> ActionResult:
    try:
        process = await asyncio.create_subprocess_shell(
            _shell_command(hook.action.command),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        return ActionResult(False, reason=f"shell failed to start: {exc}")
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(context.json().encode("utf-8")),
            timeout=hook.timeout_seconds,
        )
    except TimeoutError:
        process.kill()
        await process.communicate()
        return ActionResult(
            False, reason=f"shell timed out after {hook.timeout_seconds:g}s"
        )
    output = (stderr or stdout).decode("utf-8", errors="replace").rstrip()
    if process.returncode == 0:
        return ActionResult(True)
    if blocking and process.returncode == 2:
        return ActionResult(True, blocked=True, reason=output or "Hook 拒绝了该操作")
    return ActionResult(
        False, reason=output or f"shell exited with {process.returncode}"
    )


def _shell_command(command: str) -> str:
    if os.name != "nt":
        return command
    return _replace_unquoted_semicolons(command)


def _replace_unquoted_semicolons(command: str) -> str:
    parts: list[str] = []
    quote = ""
    escaped = False
    for char in command:
        if escaped:
            parts.append(char)
            escaped = False
            continue
        if char == "\\":
            parts.append(char)
            escaped = True
            continue
        if char in {"'", '"'}:
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
            parts.append(char)
            continue
        parts.append("&" if char == ";" and not quote else char)
    return "".join(parts)


async def _http(hook: Hook, context: HookContext, *, blocking: bool) -> ActionResult:
    try:
        body = _http_body(hook, context)
    except Exception as exc:
        return ActionResult(False, reason=f"http body render failed: {exc}")
    try:
        status, response = await asyncio.wait_for(
            asyncio.to_thread(_request, hook, body), timeout=hook.timeout_seconds
        )
    except TimeoutError:
        return ActionResult(
            False, reason=f"http timed out after {hook.timeout_seconds:g}s"
        )
    except Exception as exc:
        return ActionResult(False, reason=f"http failed: {exc}")
    if blocking and 200 <= status < 300:
        try:
            payload = json.loads(response)
        except json.JSONDecodeError:
            return ActionResult(False, reason="http response is not valid JSON")
        if isinstance(payload, dict) and payload.get("decision") == "block":
            reason = payload.get("reason")
            if isinstance(reason, str) and reason:
                return ActionResult(True, blocked=True, reason=reason)
            return ActionResult(False, reason="http block response has no reason")
    if 200 <= status < 300:
        return ActionResult(True)
    return ActionResult(False, reason=f"http returned status {status}")


def _http_body(hook: Hook, context: HookContext) -> str:
    if hook.action.body is None:
        return context.json()
    return hook.action.body.format_map(_FormatValues(context.payload))


class _FormatValues(dict[str, Any]):
    def __missing__(self, key: str) -> Any:
        raise KeyError(key)


def _request(hook: Hook, body: str) -> tuple[int, str]:
    headers = {"Content-Type": "application/json", **hook.action.headers}
    request = urllib.request.Request(
        hook.action.url,
        data=body.encode("utf-8"),
        headers=headers,
        method=hook.action.method,
    )
    try:
        with urllib.request.urlopen(request, timeout=hook.timeout_seconds) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
