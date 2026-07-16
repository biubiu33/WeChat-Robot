from __future__ import annotations

import re


# 这是启发式的最后防线，不可由任何配置或权限模式放开。
BLACKLIST: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\brm\s+(?=[^;\r\n]*(?:-[a-z]*r[a-z]*|--recursive))"
        r"(?=[^;\r\n]*(?:-[a-z]*f[a-z]*|--force))[^;\r\n]*"
        r"(?:^|\s)(?:/(?:\*+)?|~/?(?:\*+)?|\$HOME/?(?:\*+)?)(?:\s|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bdd\b[^;\r\n]*\bof\s*=\s*/dev/(?:sd|hd|vd|nvme|disk|loop|mapper)",
        re.IGNORECASE,
    ),
    re.compile(r":\s*\(\s*\)\s*\{[^}]*\|\s*&[^}]*\}", re.IGNORECASE),
    re.compile(r"\bmkfs(?:\.[\w-]+)?\b", re.IGNORECASE),
    re.compile(r">\s*/dev/(?:sd|hd|vd|nvme|disk|loop|mapper)", re.IGNORECASE),
    re.compile(r"\bchmod\s+(?=[^;\r\n]*-[a-z]*r)[^;\r\n]*\b0?777\s+/", re.IGNORECASE),
    re.compile(
        r"\bremove-item\b(?=[^;\r\n]*(?:-recurse|-r\b))"
        r"(?=[^;\r\n]*(?:-force|-f\b))",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:del|erase|rd|rmdir)\b(?=[^;\r\n]*/s\b)(?=[^;\r\n]*/q\b)",
        re.IGNORECASE,
    ),
    re.compile(r"\bformat\b", re.IGNORECASE),
    re.compile(r"\bdiskpart\b", re.IGNORECASE),
    re.compile(r"\bclear-disk\b", re.IGNORECASE),
)


def blacklist_match(command: str) -> str | None:
    for pattern in BLACKLIST:
        matched = pattern.search(command)
        if matched is not None:
            return matched.group(0).strip()
    return None


def hits_blacklist(command: str) -> bool:
    return blacklist_match(command) is not None
