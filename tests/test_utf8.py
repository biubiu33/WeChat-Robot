from __future__ import annotations

from pathlib import Path


TEXT_SUFFIXES = {".py", ".md", ".toml", ".yaml", ".yml", ".example"}
SKIP_PARTS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache"}


def iter_text_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in TEXT_SUFFIXES
        and not any(part in SKIP_PARTS for part in path.parts)
    ]


def test_project_text_files_are_utf8() -> None:
    root = Path(__file__).resolve().parents[1]

    for path in iter_text_files(root):
        path.read_text(encoding="utf-8")


def test_project_text_files_have_no_replacement_character() -> None:
    root = Path(__file__).resolve().parents[1]

    for path in iter_text_files(root):
        text = path.read_text(encoding="utf-8")
        assert "\ufffd" not in text, f"{path} 包含 Unicode replacement character"
