from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mewcode.hook.actions import execute_action
from mewcode.hook.model import Action, Hook, HookContext, HookEvent, HookSessionState


def run(coro):
    return asyncio.run(coro)


def hook(action: Action, *, timeout: float = 1) -> Hook:
    return Hook("test", HookEvent.PRE_TOOL_USE, None, action, timeout_seconds=timeout)


def context() -> HookContext:
    return HookContext(
        HookEvent.PRE_TOOL_USE,
        {"event": "PreToolUse", "tool_name": "write_file", "number": 2},
    )


def test_shell_receives_sorted_json_and_exit_two_blocks() -> None:
    command = (
        f'"{sys.executable}" -c '
        '"import json,sys; value=json.load(sys.stdin); '
        "assert list(value)==sorted(value); print(value['tool_name'], file=sys.stderr); "
        'raise SystemExit(2)"'
    )

    result = run(
        execute_action(
            hook(Action("shell", command=command)),
            context(),
            HookSessionState(),
            blocking=True,
        )
    )

    assert result.success and result.blocked
    assert result.reason == "write_file"


def test_windows_shell_accepts_posix_style_rejection_delimiter() -> None:
    if os.name != "nt":
        return

    result = run(
        execute_action(
            hook(Action("shell", command="echo blocked >&2; exit 2")),
            context(),
            HookSessionState(),
            blocking=True,
        )
    )

    assert result.success and result.blocked
    assert "blocked" in result.reason


def test_prompt_is_queued_verbatim_and_subagent_is_placeholder(capsys) -> None:
    state = HookSessionState()

    prompt_result = run(
        execute_action(
            hook(Action("prompt", text="  保持原文\\n")),
            context(),
            state,
            blocking=True,
        )
    )
    subagent_result = run(
        execute_action(
            hook(Action("subagent", agent_name="helper", prompt="x")),
            context(),
            state,
            blocking=False,
        )
    )

    assert prompt_result.success and not prompt_result.blocked
    assert subagent_result.success
    assert state.reminders == ["  保持原文\\n"]
    assert (
        "[hook subagent] not yet implemented, skipped: test" in capsys.readouterr().err
    )


def test_shell_timeout_is_a_failure() -> None:
    command = f'"{sys.executable}" -c "import time; time.sleep(1)"'

    result = run(
        execute_action(
            hook(Action("shell", command=command), timeout=0.01),
            context(),
            HookSessionState(),
            blocking=False,
        )
    )

    assert not result.success
    assert "timed out" in result.reason


def test_http_body_only_formats_payload_fields() -> None:
    action = Action("http", url="https://example.test", body="{tool_name}:{number}")
    from mewcode.hook.actions import _http_body

    assert _http_body(hook(action), context()) == "write_file:2"
    assert json.loads(
        _http_body(hook(Action("http", url="https://example.test")), context())
    ) == {
        "event": "PreToolUse",
        "number": 2,
        "tool_name": "write_file",
    }


def test_http_block_response_rejects_and_receives_default_json() -> None:
    received: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            size = int(self.headers["Content-Length"])
            received.append(json.loads(self.rfile.read(size)))
            body = b'{"decision":"block","reason":"network policy"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/policy"
        result = run(
            execute_action(
                hook(Action("http", url=url)),
                context(),
                HookSessionState(),
                blocking=True,
            )
        )
    finally:
        server.shutdown()
        thread.join()
        server.server_close()

    assert result.success and result.blocked
    assert result.reason == "network policy"
    assert received == [{"event": "PreToolUse", "number": 2, "tool_name": "write_file"}]
