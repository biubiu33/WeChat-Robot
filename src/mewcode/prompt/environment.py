"""动态运行环境信息。"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GIT_TIMEOUT_SECONDS = 2.0
MAX_GIT_STATUS_CHARS = 1_000


@dataclass(frozen=True)
class Environment:
    """一轮请求可见的非敏感运行环境快照。"""

    working_dir: str
    platform: str
    date: str
    git_status: str
    version: str
    model: str

    def render(self) -> str:
        """以独立系统段渲染所有可用环境事实。"""
        entries = (
            ("工作目录", self.working_dir),
            ("平台", self.platform),
            ("当前日期", self.date),
            ("Git 状态", self.git_status),
            ("应用版本", self.version),
            ("当前模型", self.model),
        )
        lines = [f"{name}: {value}" for name, value in entries if value]
        return "环境信息\n" + "\n".join(lines) if lines else "环境信息"


def gather_environment(
    version: str,
    model: str,
    *,
    cwd: Path | None = None,
    today: dt.date | None = None,
) -> Environment:
    """采集环境信息；无法取得 git 状态时降级为空字符串。"""
    try:
        working_dir = str((cwd if cwd is not None else Path.cwd()).resolve())
    except OSError:
        working_dir = ""

    try:
        git_status = _read_git_status(Path(working_dir)) if working_dir else ""
    except (OSError, subprocess.SubprocessError):
        git_status = ""

    current_date = today if today is not None else dt.date.today()
    return Environment(
        working_dir=working_dir,
        platform=sys.platform,
        date=current_date.isoformat(),
        git_status=git_status,
        version=version,
        model=model,
    )


def _read_git_status(cwd: Path) -> str:
    completed = subprocess.run(
        ["git", "status", "--porcelain", "--branch"],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=GIT_TIMEOUT_SECONDS,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()[:MAX_GIT_STATUS_CHARS]
