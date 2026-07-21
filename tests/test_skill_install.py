from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from mewcode.skill import SkillInstaller, SkillValidationError

from test_skill_catalog import write_skill


def build_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, content in entries.items():
            bundle.writestr(name, content)


def packaged_skill(tmp_path: Path, *, name: str = "installed") -> Path:
    source = tmp_path / "source" / "package" / "SKILL.md"
    write_skill(source, name=name)
    archive = tmp_path / "skill.zip"
    build_zip(archive, {"package/SKILL.md": source.read_text(encoding="utf-8")})
    return archive


def test_installer_installs_valid_local_directory_skill(tmp_path: Path) -> None:
    archive = packaged_skill(tmp_path)
    root = tmp_path / "user" / "skills"

    installed = SkillInstaller(root, {"read_file"}).install(str(archive))

    assert installed.skill.metadata.name == "installed"
    assert installed.path == root / "installed"
    assert (installed.path / "SKILL.md").is_file()


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ({"../escape.txt": "bad"}, "不安全"),
        ({"package/not-skill.md": "bad"}, "SKILL.md"),
    ],
)
def test_installer_rejects_unsafe_or_invalid_archives(
    tmp_path: Path, entries: dict[str, str], message: str
) -> None:
    archive = tmp_path / "bad.zip"
    build_zip(archive, entries)

    with pytest.raises(SkillValidationError, match=message):
        SkillInstaller(tmp_path / "user" / "skills", {"read_file"}).install(
            str(archive)
        )


def test_installer_rejects_http_unknown_tools_and_existing_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "user" / "skills"
    installer = SkillInstaller(root, {"read_file"})

    with pytest.raises(SkillValidationError, match="HTTPS"):
        installer.install("http://example.test/skill.zip")

    source = tmp_path / "source" / "package" / "SKILL.md"
    write_skill(source, name="bad", tools="[missing]")
    invalid = tmp_path / "invalid.zip"
    build_zip(invalid, {"package/SKILL.md": source.read_text(encoding="utf-8")})
    with pytest.raises(SkillValidationError, match="missing"):
        installer.install(str(invalid))

    archive = packaged_skill(tmp_path, name="same")
    installer.install(str(archive))
    with pytest.raises(SkillValidationError, match="已存在"):
        installer.install(str(archive))
