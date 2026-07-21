from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


SKILL_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


class SkillError(ValueError):
    pass


class SkillParseError(SkillError):
    pass


class SkillValidationError(SkillError):
    pass


class SkillMode(str, Enum):
    INLINE = "inline"
    FORK = "fork"


class SkillSource(str, Enum):
    PROJECT = "project"
    USER = "user"
    BUILTIN = "builtin"


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    allowed_tools: frozenset[str]
    mode: SkillMode
    fork_history: str
    model: str | None = None


@dataclass(frozen=True)
class SkillDiagnostic:
    path: Path
    message: str


@dataclass(frozen=True)
class Skill:
    metadata: SkillMetadata
    source: SkillSource
    entry_path: Path
    package_root: Path

    def load_instruction(self, argument: str) -> str:
        try:
            content = self.entry_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillParseError(f"无法读取 Skill: {self.entry_path}: {exc}") from exc
        body = skill_body(content)
        return body.replace("{{args}}", argument)


@dataclass(frozen=True)
class ActiveSkill:
    name: str
    argument: str
    instruction: str
    allowed_tools: frozenset[str]
    model: str | None


def skill_body(content: str) -> str:
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillParseError("Skill 必须以 YAML frontmatter 开始")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body = "".join(lines[index + 1 :]).strip()
            if not body:
                raise SkillParseError("Skill 正文不能为空")
            return body
    raise SkillParseError("Skill frontmatter 缺少结束标记")


__all__ = [
    "ActiveSkill",
    "SKILL_NAME_RE",
    "Skill",
    "SkillDiagnostic",
    "SkillError",
    "SkillMetadata",
    "SkillMode",
    "SkillParseError",
    "SkillSource",
    "SkillValidationError",
    "skill_body",
]
