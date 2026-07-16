from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mewcode.llm import ToolCall

from . import Category, Decision, Mode, parse_mode
from .blacklist import BLACKLIST
from .rule import RuleSet
from .sandbox import resolve_root, resolve_target, sandbox_ok
from .settings import (
    Settings,
    categorize,
    extract_target,
    friendly_name,
    load_settings,
    to_rule_set,
)


@dataclass
class Engine:
    root: Path
    blacklist: tuple[re.Pattern[str], ...] = BLACKLIST
    session: RuleSet = field(default_factory=RuleSet)
    user: RuleSet = field(default_factory=RuleSet)
    project: RuleSet = field(default_factory=RuleSet)
    local: RuleSet = field(default_factory=RuleSet)
    local_path: Path = field(default_factory=Path)
    default_mode: Mode = Mode.DEFAULT

    def check(
        self,
        mode: Mode,
        call: ToolCall,
        read_only: bool,
    ) -> tuple[Decision, str]:
        return check(self, mode, call, read_only)

    def resolve_file_target(self, target: str) -> Path:
        return resolve_target(self.root, target)

    def allow_session(self, call: ToolCall) -> None:
        from .persist import allow_session

        allow_session(self, call)

    def persist_local_allow(self, call: ToolCall) -> None:
        from .persist import persist_local_allow

        persist_local_allow(self, call)


def new_engine(
    root: str | Path,
    *,
    home: Path | None = None,
) -> tuple[Engine, Exception | None]:
    """构造权限引擎，配置错误降级为空规则，不中断启动。"""

    try:
        resolved_root = resolve_root(root)
    except OSError as exc:
        fallback_root = Path(root).expanduser().resolve(strict=False)
        local_path = fallback_root / ".mewcode" / "settings.local.yaml"
        return Engine(root=fallback_root, local_path=local_path), exc

    home_dir = Path.home() if home is None else home
    user_settings = load_settings(home_dir / ".mewcode" / "settings.yaml")
    project_settings = load_settings(resolved_root / ".mewcode" / "settings.yaml")
    local_path = resolved_root / ".mewcode" / "settings.local.yaml"
    local_settings = load_settings(local_path)
    default_mode = _select_default_mode(local_settings, project_settings, user_settings)
    return (
        Engine(
            root=resolved_root,
            user=to_rule_set(user_settings),
            project=to_rule_set(project_settings),
            local=to_rule_set(local_settings),
            local_path=local_path,
            default_mode=default_mode,
        ),
        None,
    )


def check(
    engine: Engine,
    mode: Mode,
    call: ToolCall,
    read_only: bool,
) -> tuple[Decision, str]:
    """执行黑名单、沙箱、规则和模式四层判定。"""

    category = categorize(call.name, read_only)
    target, is_file, ok = extract_target(call)

    if call.name == "bash" and target:
        hit = _blacklist_hit(engine, target)
        if hit is not None:
            return Decision.DENY, f"命中危险命令黑名单：{hit}"

    if call.name == "bash" and not ok:
        return Decision.ASK, "无法解析命令参数，安全要求确认"

    resolved: Path | None = None
    if is_file:
        if not ok:
            return Decision.DENY, "无法解析文件路径参数，安全拒绝"
        if not sandbox_ok(engine.root, target):
            return Decision.DENY, f"路径在项目目录之外：{target}"
        resolved = engine.resolve_file_target(target)

    friendly = friendly_name(call.name)
    rule_target = (
        resolved.relative_to(engine.root).as_posix() if resolved is not None else target
    )
    for rules in (engine.session, engine.local, engine.project, engine.user):
        decision, rule = rules.match(friendly, rule_target, is_path=is_file)
        if decision is Decision.DENY:
            assert rule is not None
            return Decision.DENY, f"匹配 deny 规则：{rule.render()}"
        if decision is Decision.ALLOW:
            return Decision.ALLOW, ""

    fallback = mode_fallback(mode, category)
    if fallback is Decision.ASK:
        return Decision.ASK, f"{mode} 模式下 {_category_name(category)} 类操作需确认"
    return Decision.ALLOW, ""


def mode_fallback(mode: Mode, category: Category) -> Decision:
    if category is Category.READ or mode is Mode.BYPASS:
        return Decision.ALLOW
    if mode is Mode.ACCEPT_EDITS and category is Category.WRITE:
        return Decision.ALLOW
    return Decision.ASK


def _select_default_mode(*settings: Settings) -> Mode:
    for setting in settings:
        mode, valid = parse_mode(setting.default_mode)
        if valid:
            return mode
    return Mode.DEFAULT


def _blacklist_hit(engine: Engine, command: str) -> str | None:
    for pattern in engine.blacklist:
        matched = pattern.search(command)
        if matched is not None:
            return matched.group(0).strip()
    return None


def _category_name(category: Category) -> str:
    return {
        Category.READ: "只读",
        Category.WRITE: "文件写入",
        Category.EXEC: "命令执行",
    }[category]
