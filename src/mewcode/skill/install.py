from __future__ import annotations

import os
import shutil
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .catalog import parse_skill, validate_allowed_tools
from .model import Skill, SkillParseError, SkillSource, SkillValidationError


MAX_ARCHIVE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class InstalledSkill:
    skill: Skill
    path: Path


class SkillInstaller:
    def __init__(self, user_root: Path, ordinary_tools: set[str]) -> None:
        self._user_root = user_root.resolve()
        self._ordinary_tools = ordinary_tools

    def install(self, source: str) -> InstalledSkill:
        self._user_root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._user_root.parent) as temporary:
            temporary_path = Path(temporary)
            archive = self._obtain_archive(source, temporary_path)
            package = _extract_package(archive, temporary_path / "extract")
            skill = parse_skill(package / "SKILL.md", SkillSource.USER, package)
            try:
                validate_allowed_tools((skill,), self._ordinary_tools)
            except SkillParseError as exc:
                raise SkillValidationError(str(exc)) from exc
            target = self._user_root / skill.metadata.name
            if target.exists():
                raise SkillValidationError(f"目标 Skill 已存在: {skill.metadata.name}")
            self._user_root.mkdir(parents=True, exist_ok=True)
            os.replace(package, target)
            installed = parse_skill(target / "SKILL.md", SkillSource.USER, target)
            return InstalledSkill(installed, target)

    def _obtain_archive(self, source: str, temporary: Path) -> Path:
        path = Path(source).expanduser()
        if path.is_file():
            if path.suffix.lower() != ".zip":
                raise SkillValidationError("Skill 安装只接受本地 ZIP 文件")
            target = temporary / "skill.zip"
            shutil.copyfile(path, target)
            if target.stat().st_size > MAX_ARCHIVE_BYTES:
                raise SkillValidationError("Skill ZIP 超过大小限制")
            return target
        parsed = urllib.parse.urlparse(source)
        if parsed.scheme:
            if parsed.scheme != "https":
                raise SkillValidationError("Skill 安装只接受 HTTPS URL")
            return _download(source, temporary / "skill.zip")
        raise SkillValidationError("Skill 安装只接受本地 ZIP 文件")


def _download(source: str, target: Path) -> Path:
    try:
        with urllib.request.urlopen(source, timeout=30) as response:
            final_scheme = urllib.parse.urlparse(response.geturl()).scheme
            if final_scheme != "https":
                raise SkillValidationError("Skill 安装重定向到了非 HTTPS URL")
            total = 0
            with target.open("wb") as output:
                while chunk := response.read(64 * 1024):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise SkillValidationError("Skill ZIP 超过大小限制")
                    output.write(chunk)
    except SkillValidationError:
        raise
    except OSError as exc:
        raise SkillValidationError(f"无法下载 Skill ZIP: {exc}") from exc
    return target


def _extract_package(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                relative = PurePosixPath(item.filename)
                if _unsafe_member(relative, item):
                    raise SkillValidationError(
                        f"Skill ZIP 包含不安全条目: {item.filename}"
                    )
                target = destination.joinpath(*relative.parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(item) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise SkillValidationError("Skill 来源不是有效 ZIP 文件") from exc
    return _package_root(destination)


def _unsafe_member(path: PurePosixPath, item: zipfile.ZipInfo) -> bool:
    mode = item.external_attr >> 16
    return (
        path.is_absolute() or not path.parts or ".." in path.parts or stat.S_ISLNK(mode)
    )


def _package_root(destination: Path) -> Path:
    if (destination / "SKILL.md").is_file():
        return destination
    entries = list(destination.iterdir())
    if (
        len(entries) == 1
        and entries[0].is_dir()
        and (entries[0] / "SKILL.md").is_file()
    ):
        return entries[0]
    raise SkillValidationError("Skill ZIP 必须包含唯一的目录型 SKILL.md 入口")


__all__ = ["InstalledSkill", "MAX_ARCHIVE_BYTES", "SkillInstaller"]
