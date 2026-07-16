"""MewCode 工具权限判定。"""

from __future__ import annotations

from enum import IntEnum


class Mode(IntEnum):
    """规则未命中时的权限兜底模式。"""

    DEFAULT = 0
    ACCEPT_EDITS = 1
    PLAN = 2
    BYPASS = 3
    # 保留旧 API 兼容性；新代码统一使用 DEFAULT。
    NORMAL = DEFAULT

    def __str__(self) -> str:
        return {
            Mode.DEFAULT: "default",
            Mode.ACCEPT_EDITS: "acceptEdits",
            Mode.PLAN: "plan",
            Mode.BYPASS: "bypassPermissions",
        }[self]


class Decision(IntEnum):
    ALLOW = 0
    DENY = 1
    ASK = 2


class Category(IntEnum):
    READ = 0
    WRITE = 1
    EXEC = 2


class Outcome(IntEnum):
    """用户对一次待批准工具调用作出的决定。"""

    ALLOW_ONCE = 0
    ALLOW_SESSION = 1
    ALLOW_FOREVER = 2
    DENY_ONCE = 3


def parse_mode(value: str) -> tuple[Mode, bool]:
    """解析配置中的模式名，未知值回退为 default。"""

    normalized = value.strip().lower() if isinstance(value, str) else ""
    mapping = {
        "default": Mode.DEFAULT,
        "acceptedits": Mode.ACCEPT_EDITS,
        "plan": Mode.PLAN,
        "bypasspermissions": Mode.BYPASS,
    }
    mode = mapping.get(normalized)
    return (mode, True) if mode is not None else (Mode.DEFAULT, False)


from .engine import Engine, check, mode_fallback, new_engine  # noqa: E402
from .persist import allow_session, persist_local_allow  # noqa: E402
from .rule import Rule, RuleSet  # noqa: E402


__all__ = [
    "Category",
    "Decision",
    "Engine",
    "Mode",
    "Outcome",
    "Rule",
    "RuleSet",
    "allow_session",
    "check",
    "mode_fallback",
    "new_engine",
    "parse_mode",
    "persist_local_allow",
]
