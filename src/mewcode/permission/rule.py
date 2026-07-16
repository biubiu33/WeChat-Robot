from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import Decision


@dataclass(frozen=True)
class Rule:
    tool: str
    pattern: str
    allow: bool

    def render(self) -> str:
        return self.tool if not self.pattern else f"{self.tool}({self.pattern})"


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


def parse_rule(value: object, *, allow: bool) -> Rule | None:
    """解析 Bash(git *) 或 Write(src/**) 形式的规则。"""

    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if "(" not in text:
        return Rule(tool=text, pattern="", allow=allow)
    if not text.endswith(")"):
        return None
    tool, pattern = text.split("(", 1)
    tool = tool.strip()
    pattern = pattern[:-1]
    if not tool:
        return None
    return Rule(tool=tool, pattern=pattern, allow=allow)


def match_pattern(pattern: str, target: str, *, is_path: bool) -> bool:
    """将权限规则 glob 转为完整匹配正则。"""

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
    return tool_matches and match_pattern(rule.pattern, target, is_path=is_path)
