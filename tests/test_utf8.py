from __future__ import annotations

from pathlib import Path


TEXT_SUFFIXES = {".py", ".md", ".toml", ".yaml", ".example", ".gitignore"}


def test_project_text_files_are_utf8() -> None:
    root = Path(__file__).resolve().parents[1]
    for path in root.rglob("*"):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        if path.is_file() and (
            path.suffix in TEXT_SUFFIXES or path.name == ".gitignore"
        ):
            text = path.read_text(encoding="utf-8")
            assert "\ufffd" not in text, str(path)
