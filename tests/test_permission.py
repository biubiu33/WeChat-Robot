from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.llm import ToolCall
from mewcode.permission import (
    Category,
    Decision,
    Mode,
    Rule,
    RuleSet,
    allow_session,
    check,
    mode_fallback,
    new_engine,
    persist_local_allow,
)
from mewcode.permission.blacklist import blacklist_match
from mewcode.permission.rule import (
    Pattern,
    match_pattern,
    parse_rule,
    parse_rule_detail,
)


def call(name: str, values: str) -> ToolCall:
    return ToolCall("call-id", name, values)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "rm -fr ~",
        "rm -rf /*",
        "dd if=/dev/zero of=/dev/sda",
        "mkfs.ext4 /dev/sda1",
        "Remove-Item -Recurse -Force C:\\",
        "del /s /q C:\\temp",
        "format C:",
        "diskpart",
        "Clear-Disk -Number 0",
    ],
)
def test_dangerous_commands_are_blacklisted(command: str) -> None:
    assert blacklist_match(command) is not None


def test_blacklist_cannot_be_bypassed(tmp_path: Path) -> None:
    engine, err = new_engine(tmp_path)

    assert err is None
    decision, reason = check(
        engine, Mode.BYPASS, call("bash", '{"command":"rm -rf /"}'), False
    )

    assert decision is Decision.DENY
    assert "危险命令黑名单" in reason


def test_sandbox_allows_project_paths_and_denies_escaping(tmp_path: Path) -> None:
    engine, err = new_engine(tmp_path)

    assert err is None
    inside, _ = check(
        engine,
        Mode.DEFAULT,
        call("write_file", '{"path":"nested/new/file.txt","content":"x"}'),
        False,
    )
    outside, reason = check(
        engine,
        Mode.DEFAULT,
        call("write_file", '{"path":"../outside.txt","content":"x"}'),
        False,
    )
    windows_absolute, _ = check(
        engine,
        Mode.BYPASS,
        call("write_file", '{"path":"C:\\\\outside\\\\file.txt","content":"x"}'),
        False,
    )

    assert inside is Decision.ASK
    assert outside is Decision.DENY
    assert windows_absolute is Decision.DENY
    assert "项目目录之外" in reason


def test_sandbox_resolves_symlink_before_prefix_check(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前环境不允许创建符号链接")
    engine, err = new_engine(tmp_path)

    assert err is None
    decision, _ = check(
        engine,
        Mode.DEFAULT,
        call("read_file", '{"path":"escape/secret.txt"}'),
        True,
    )

    assert decision is Decision.DENY


def test_rule_parser_and_globs() -> None:
    rule = parse_rule("Bash(git *)", allow=True)

    assert rule == Rule("Bash", "git *", True)
    assert parse_rule("Read", allow=True) == Rule("Read", "", True)
    assert parse_rule("broken(", allow=True) is None
    assert match_pattern("git *", "git status", is_path=False)
    assert not match_pattern("git *", "hg status", is_path=False)
    assert match_pattern("src/**", "src/mewcode/agent.py", is_path=True)
    assert not match_pattern("src/*", "src/mewcode/agent.py", is_path=True)


@pytest.mark.parametrize(
    ("rule_text", "target", "expected"),
    [
        ("Bash(=git status)", "git status", True),
        ("Bash(=git status)", "git status -s", False),
        ("Bash(~^npm (install|test)$)", "npm install", True),
        ("Bash(~^npm (install|test)$)", "npm run dev", False),
        ("Bash(!~^rm.*)", "ls -lh", True),
        ("Bash(!~^rm.*)", "rm -rf .", False),
    ],
)
def test_rule_parser_supports_explicit_patterns(
    rule_text: str, target: str, expected: bool
) -> None:
    rule = parse_rule(rule_text, allow=True)

    assert rule is not None
    assert rule.pattern is not None
    assert rule.pattern.matches(target, is_path=False) is expected


def test_pattern_supports_nested_not_and_reports_invalid_regex() -> None:
    pattern = Pattern("not", inner=Pattern("not", inner=Pattern("exact", "x")))
    rule, reason = parse_rule_detail("Bash(~[)", allow=True)

    assert pattern.matches("x", is_path=False)
    assert rule is None
    assert "正则无效" in reason


def test_same_layer_deny_wins_over_allow() -> None:
    rules = RuleSet(
        allow=[Rule("Bash", "git *", True)],
        deny=[Rule("Bash", "git push", False)],
    )

    decision, rule = rules.match("Bash", "git push", is_path=False)

    assert decision is Decision.DENY
    assert rule == Rule("Bash", "git push", False)


def test_rule_layer_priority_and_friendly_names(tmp_path: Path) -> None:
    mewcode = tmp_path / ".mewcode"
    mewcode.mkdir()
    (mewcode / "settings.yaml").write_text(
        "permissions:\n  allow:\n    - 'Write(src/**)'\n", encoding="utf-8"
    )
    (mewcode / "settings.local.yaml").write_text(
        "permissions:\n  deny:\n    - 'Write(src/locked.py)'\n", encoding="utf-8"
    )
    home = tmp_path / "home"
    (home / ".mewcode").mkdir(parents=True)
    (home / ".mewcode" / "settings.yaml").write_text(
        "permissions:\n  allow:\n    - 'Bash(git *)'\n", encoding="utf-8"
    )
    engine, err = new_engine(tmp_path, home=home)

    assert err is None
    allowed, _ = check(
        engine,
        Mode.DEFAULT,
        call("write_file", '{"path":"src/new.py","content":"x"}'),
        False,
    )
    denied, reason = check(
        engine,
        Mode.BYPASS,
        call("write_file", '{"path":"src/locked.py","content":"x"}'),
        False,
    )
    bash, _ = check(
        engine, Mode.DEFAULT, call("bash", '{"command":"git status"}'), False
    )

    assert allowed is Decision.ALLOW
    assert denied is Decision.DENY and "Write(src/locked.py)" in reason
    assert bash is Decision.ALLOW


@pytest.mark.parametrize(
    ("mode", "category", "expected"),
    [
        (Mode.DEFAULT, Category.READ, Decision.ALLOW),
        (Mode.DEFAULT, Category.WRITE, Decision.ASK),
        (Mode.DEFAULT, Category.EXEC, Decision.ASK),
        (Mode.ACCEPT_EDITS, Category.WRITE, Decision.ALLOW),
        (Mode.ACCEPT_EDITS, Category.EXEC, Decision.ASK),
        (Mode.PLAN, Category.WRITE, Decision.ASK),
        (Mode.BYPASS, Category.EXEC, Decision.ALLOW),
    ],
)
def test_mode_matrix(mode: Mode, category: Category, expected: Decision) -> None:
    assert mode_fallback(mode, category) is expected


def test_invalid_arguments_use_safe_defaults(tmp_path: Path) -> None:
    engine, err = new_engine(tmp_path)

    assert err is None
    file_decision, _ = check(engine, Mode.BYPASS, call("write_file", "not json"), False)
    bash_decision, _ = check(engine, Mode.BYPASS, call("bash", "{}"), False)
    unknown_decision, _ = check(engine, Mode.DEFAULT, call("unknown", "{}"), False)

    assert file_decision is Decision.DENY
    assert bash_decision is Decision.ASK
    assert unknown_decision is Decision.ASK


def test_unknown_tool_uses_safe_default_mode(tmp_path: Path) -> None:
    engine, err = new_engine(tmp_path)

    assert err is None
    decision, reason = check(engine, Mode.DEFAULT, call("unknown", "{}"), False)

    assert decision is Decision.ASK
    assert "命令执行" in reason


def test_mcp_tools_follow_read_only_and_rule_permissions(tmp_path: Path) -> None:
    engine, err = new_engine(tmp_path)
    read = call("mcp__demo__search", "{}")
    write = call("mcp__demo__publish", "{}")

    assert err is None
    read_decision, _ = check(engine, Mode.DEFAULT, read, True)
    write_decision, _ = check(engine, Mode.DEFAULT, write, False)

    assert read_decision is Decision.ALLOW
    assert write_decision is Decision.ASK

    engine.user.allow.append(Rule("mcp__demo__*", "", allow=True))
    allowed_write, _ = check(engine, Mode.DEFAULT, write, False)
    other_write, _ = check(
        engine, Mode.DEFAULT, call("mcp__other__publish", "{}"), False
    )

    assert allowed_write is Decision.ALLOW
    assert other_write is Decision.ASK


def test_default_mode_uses_nearest_valid_setting(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".mewcode").mkdir(parents=True)
    (home / ".mewcode" / "settings.yaml").write_text(
        "default_mode: plan\n", encoding="utf-8"
    )
    project = tmp_path / "project"
    (project / ".mewcode").mkdir(parents=True)
    (project / ".mewcode" / "settings.yaml").write_text(
        "default_mode: acceptEdits\n", encoding="utf-8"
    )
    (project / ".mewcode" / "settings.local.yaml").write_text(
        "default_mode: bypassPermissions\n", encoding="utf-8"
    )

    engine, err = new_engine(project, home=home)

    assert err is None
    assert engine.default_mode is Mode.BYPASS


def test_session_and_persistent_allows_are_exact(tmp_path: Path) -> None:
    engine, err = new_engine(tmp_path)
    write = call("write_file", '{"path":"src/a.py","content":"x"}')

    assert err is None
    before, _ = check(engine, Mode.DEFAULT, write, False)
    allow_session(engine, write)
    session, _ = check(engine, Mode.DEFAULT, write, False)
    rebuilt, err = new_engine(tmp_path)
    after_rebuild, _ = check(rebuilt, Mode.DEFAULT, write, False)
    persist_local_allow(engine, write)
    persisted, err = new_engine(tmp_path)
    after_persist, _ = check(persisted, Mode.DEFAULT, write, False)

    assert err is None
    assert before is Decision.ASK
    assert session is Decision.ALLOW
    assert after_rebuild is Decision.ASK
    assert after_persist is Decision.ALLOW
    assert "Write(src/a.py)" in engine.local_path.read_text(encoding="utf-8")


def test_session_rule_overrides_local_rule(tmp_path: Path) -> None:
    engine, err = new_engine(tmp_path)
    write = call("write_file", '{"path":"src/a.py","content":"x"}')
    engine.local.deny.append(Rule("Write", "src/a.py", allow=False))

    assert err is None
    denied, _ = check(engine, Mode.BYPASS, write, False)
    allow_session(engine, write)
    allowed, _ = check(engine, Mode.DEFAULT, write, False)

    assert denied is Decision.DENY
    assert allowed is Decision.ALLOW


def test_subagent_engine_snapshots_only_parent_session_allows(tmp_path: Path) -> None:
    engine, err = new_engine(tmp_path)
    first = call("write_file", '{"path":"src/a.py","content":"x"}')
    later = call("write_file", '{"path":"src/b.py","content":"x"}')

    assert err is None
    allow_session(engine, first)
    child = engine.fork_for_subagent()
    allow_session(engine, later)
    allow_session(child, call("write_file", '{"path":"src/c.py","content":"x"}'))

    assert check(child, Mode.DEFAULT, first, False)[0] is Decision.ALLOW
    assert check(child, Mode.DEFAULT, later, False)[0] is Decision.ASK
    assert check(engine, Mode.DEFAULT, call("write_file", '{"path":"src/c.py","content":"x"}'), False)[0] is Decision.ASK


def test_subagent_allow_forever_updates_shared_local_rules(tmp_path: Path) -> None:
    engine, err = new_engine(tmp_path)
    child = engine.fork_for_subagent()
    write = call("write_file", '{"path":"src/a.py","content":"x"}')

    assert err is None
    persist_local_allow(child, write)

    assert check(engine, Mode.DEFAULT, write, False)[0] is Decision.ALLOW
    assert "Write(src/a.py)" in engine.local_path.read_text(encoding="utf-8")


def test_dont_ask_allows_only_unmatched_safe_operations(tmp_path: Path) -> None:
    engine, err = new_engine(tmp_path)

    assert err is None
    assert check(
        engine,
        Mode.DONT_ASK,
        call("write_file", '{"path":"src/a.py","content":"x"}'),
        False,
    )[0] is Decision.ALLOW
    assert check(
        engine, Mode.DONT_ASK, call("bash", '{"command":"rm -rf /"}'), False
    )[0] is Decision.DENY
    assert check(
        engine,
        Mode.DONT_ASK,
        call("write_file", '{"path":"../escape.txt","content":"x"}'),
        False,
    )[0] is Decision.DENY
