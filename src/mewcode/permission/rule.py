from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from . import Decision


PatternType = Literal["exact", "glob", "regex", "not"]


@dataclass(frozen=True)
class Pattern:
    """可供权限规则和 Hook 条件复用的已校验匹配表达式。"""

    type: PatternType
    value: str = ""
    inner: Pattern | None = None
    _compiled: re.Pattern[str] | None = field(
        default=None, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        if self.type not in {"exact", "glob", "regex", "not"}:
            raise ValueError(f"未知匹配类型: {self.type}")
        if self.type == "not":
            if self.inner is None:
                raise ValueError("not 匹配缺少 inner")
            return
        if self.inner is not None:
            raise ValueError(f"{self.type} 匹配不接受 inner")
        if self.type == "regex":
            try:
                compiled = re.compile(self.value, flags=re.DOTALL)
            except re.error as exc:
                raise ValueError(f"正则无效: {exc}") from exc
            object.__setattr__(self, "_compiled", compiled)

    def matches(self, target: str, *, is_path: bool) -> bool:
        if self.type == "not":
            assert self.inner is not None
            return not self.inner.matches(target, is_path=is_path)
        if self.type == "exact":
            return self.value == target
        if self.type == "regex":
            assert self._compiled is not None
            return self._compiled.fullmatch(target) is not None
        return _match_glob(self.value, target, is_path=is_path)

    def render(self) -> str:
        if self.type == "exact":
            return f"={self.value}"
        if self.type == "regex":
            return f"~{self.value}"
        if self.type == "not":
            assert self.inner is not None
            return f"!{self.inner.render()}"
        return self.value


@dataclass(frozen=True)
class Rule:
    tool: str
    pattern: Pattern | str | None
    allow: bool

    def __post_init__(self) -> None:
        if isinstance(self.pattern, str):
            object.__setattr__(
                self,
                "pattern",
                Pattern("glob", self.pattern) if self.pattern else None,
            )

    def render(self) -> str:
        if self.pattern is None:
            return self.tool
        assert isinstance(self.pattern, Pattern)
        return f"{self.tool}({self.pattern.render()})"


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(
        self,
        tool: str,
        target: str,
        *,
        is_path: bool,
    ) -> tuple[Decision | None, Rule | None]:
        """同层中 deny 优先于 allow。"""

        for rule in self.deny:
            if _rule_matches(rule, tool, target, is_path=is_path):
                return Decision.DENY, rule
        for rule in self.allow:
            if _rule_matches(rule, tool, target, is_path=is_path):
                return Decision.ALLOW, rule
        return None, None

    def add_allow(self, rule: Rule) -> None:
        if rule not in self.allow:
            self.allow.append(rule)


def parse_pattern(value: object) -> Pattern:
    if not isinstance(value, str):
        raise ValueError("匹配值必须是字符串")
    if value.startswith("!"):
        return Pattern("not", inner=parse_pattern(value[1:]))
    if value.startswith("="):
        return Pattern("exact", value[1:])
    if value.startswith("~"):
        return Pattern("regex", value[1:])
    return Pattern("glob", value)


def parse_rule_detail(value: object, *, allow: bool) -> tuple[Rule | None, str]:
    """解析规则并返回可显示的失败原因。"""

    if not isinstance(value, str):
        return None, "规则必须是字符串"
    text = value.strip()
    if not text:
        return None, "规则不能为空"
    if "(" not in text:
        return Rule(tool=text, pattern=None, allow=allow), ""
    if not text.endswith(")"):
        return None, "缺少结尾 )"
    tool, raw_pattern = text.split("(", 1)
    tool = tool.strip()
    if not tool:
        return None, "工具名不能为空"
    try:
        return Rule(tool=tool, pattern=parse_pattern(raw_pattern[:-1]), allow=allow), ""
    except ValueError as exc:
        return None, str(exc)


def parse_rule(value: object, *, allow: bool) -> Rule | None:
    """解析 Bash(git *)、Bash(=git status) 或 Bash(~^git ) 规则。"""

    rule, _ = parse_rule_detail(value, allow=allow)
    return rule


def match_pattern(pattern: str, target: str, *, is_path: bool) -> bool:
    """保留旧 API：按 glob 完整匹配。"""

    return Pattern("glob", pattern).matches(target, is_path=is_path)


def _match_glob(pattern: str, target: str, *, is_path: bool) -> bool:
    if not pattern:
        return True
    if is_path:
        pattern = pattern.replace("\\", "/")
        target = target.replace("\\", "/")

    fragments: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                fragments.append(".*")
                index += 2
                continue
            fragments.append("[^/]*" if is_path else ".*")
        else:
            fragments.append(re.escape(char))
        index += 1
    return re.fullmatch("".join(fragments), target, flags=re.DOTALL) is not None


def _rule_matches(rule: Rule, tool: str, target: str, *, is_path: bool) -> bool:
    tool_matches = rule.tool.casefold() == tool.casefold() or (
        rule.tool.startswith("mcp__")
        and "*" in rule.tool
        and match_pattern(rule.tool, tool, is_path=False)
    )
    if not tool_matches:
        return False
    if rule.pattern is None:
        return True
    assert isinstance(rule.pattern, Pattern)
    return rule.pattern.matches(target, is_path=is_path)
