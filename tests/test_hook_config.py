from __future__ import annotations

from pathlib import Path

from mewcode.hook import HookEvent, load_catalog


def write_hooks(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_loads_project_then_user_rules_in_declaration_order(tmp_path: Path) -> None:
    home = tmp_path / "home"
    write_hooks(
        tmp_path / ".mewcode" / "hooks.yaml",
        """hooks:
  - name: project-first
    event: SessionStart
    action: {type: prompt, text: project}
  - name: project-second
    event: Stop
    action: {type: subagent, agent_name: helper, prompt: test}
""",
    )
    write_hooks(
        home / ".mewcode" / "hooks.yaml",
        """hooks:
  - name: user-rule
    event: PreToolUse
    action: {type: shell, command: echo ok}
""",
    )

    catalog = load_catalog(tmp_path, home)

    assert [hook.name for hook in catalog.hooks] == [
        "project-first",
        "project-second",
        "user-rule",
    ]
    assert [hook.event for hook in catalog.hooks] == [
        HookEvent.SESSION_START,
        HookEvent.STOP,
        HookEvent.PRE_TOOL_USE,
    ]


def test_bad_hook_is_skipped_without_losing_other_rules(tmp_path: Path, capsys) -> None:
    write_hooks(
        tmp_path / ".mewcode" / "hooks.yaml",
        """hooks:
  - name: invalid
    event: UnknownEvent
    action: {type: prompt, text: ignored}
  - name: valid
    event: Stop
    action: {type: prompt, text: kept}
""",
    )

    catalog = load_catalog(tmp_path, tmp_path / "home")

    assert [hook.name for hook in catalog.hooks] == ["valid"]
    assert (
        'hook "invalid": unknown event "UnknownEvent", skipped'
        in capsys.readouterr().err
    )


def test_config_rejects_invalid_groups_actions_and_async_combinations(
    tmp_path: Path, capsys
) -> None:
    write_hooks(
        tmp_path / ".mewcode" / "hooks.yaml",
        """hooks:
  - name: mixed
    event: Stop
    if: {all_of: [], any_of: []}
    action: {type: prompt, text: ignored}
  - name: prompt-async
    event: Stop
    async: true
    action: {type: prompt, text: ignored}
  - name: blocking-async
    event: PreToolUse
    async: true
    action: {type: shell, command: echo ignored}
  - name: bad-regex
    event: Stop
    if:
      all_of:
        - field: prompt
          match: {type: regex, value: "["}
    action: {type: prompt, text: ignored}
  - name: valid
    event: Stop
    if:
      any_of:
        - field: prompt
          match: {type: not, inner: {type: exact, value: skip}}
    action: {type: http, url: https://example.test}
""",
    )

    catalog = load_catalog(tmp_path, tmp_path / "home")

    assert [hook.name for hook in catalog.hooks] == ["valid"]
    stderr = capsys.readouterr().err
    assert "if must contain exactly one all_of or any_of" in stderr
    assert "async not allowed for prompt actions" in stderr
    assert "async not allowed for blocking events" in stderr
    assert "invalid match" in stderr


def test_duplicate_name_skips_later_source(tmp_path: Path, capsys) -> None:
    home = tmp_path / "home"
    write_hooks(
        tmp_path / ".mewcode" / "hooks.yaml",
        """hooks:
  - name: duplicate
    event: Stop
    action: {type: prompt, text: project}
""",
    )
    write_hooks(
        home / ".mewcode" / "hooks.yaml",
        """hooks:
  - name: duplicate
    event: Stop
    action: {type: prompt, text: user}
""",
    )

    catalog = load_catalog(tmp_path, home)

    assert [hook.action.text for hook in catalog.hooks] == ["project"]
    assert 'hook "duplicate": duplicate name, skipped' in capsys.readouterr().err
