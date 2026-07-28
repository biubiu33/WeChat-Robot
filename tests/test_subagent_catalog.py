from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.subagent import (
    AgentCatalog,
    DefinitionError,
    DefinitionSource,
    PermissionMode,
    parse_definition,
)


def write_definition(
    path: Path,
    *,
    name: str = "demo",
    description: str = "A demonstration role",
    tools: str | None = None,
    disallowed: str = "[]",
    model: str = "inherit",
    max_turns: int = 5,
    permission_mode: str = "default",
    background: bool = False,
    body: str = "Complete the assigned task directly.",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tools_line = "" if tools is None else f"tools: {tools}\n"
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"{tools_line}"
        f"disallowedTools: {disallowed}\n"
        f"model: {model}\n"
        f"maxTurns: {max_turns}\n"
        f"permissionMode: {permission_mode}\n"
        f"background: {str(background).lower()}\n"
        "---\n"
        f"{body}\n",
        encoding="utf-8",
    )


def roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    return tmp_path / "project", tmp_path / "user", tmp_path / "builtin"


def test_parse_definition_preserves_declared_metadata(tmp_path: Path) -> None:
    path = tmp_path / "review.md"
    write_definition(
        path,
        name="review",
        tools="[read_file, grep]",
        disallowed="[bash]",
        model="project-haiku",
        max_turns=12,
        permission_mode="plan",
        background=True,
    )

    definition = parse_definition(path, DefinitionSource.USER)

    assert definition.name == "review"
    assert definition.tools == frozenset({"read_file", "grep"})
    assert definition.disallowed_tools == frozenset({"bash"})
    assert definition.model_profile == "project-haiku"
    assert definition.max_turns == 12
    assert definition.permission_mode is PermissionMode.PLAN
    assert definition.background is True


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": "Bad Name"}, "kebab-case"),
        ({"tools": "read_file"}, "tools"),
        ({"model": " "}, "model"),
        ({"max_turns": 0}, "maxTurns"),
        ({"permission_mode": "unsafe"}, "permissionMode"),
        ({"body": ""}, "Agent"),
    ],
)
def test_parse_definition_rejects_invalid_metadata(
    tmp_path: Path, kwargs: dict[str, object], message: str
) -> None:
    path = tmp_path / "invalid.md"
    write_definition(path, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(DefinitionError, match=message):
        parse_definition(path, DefinitionSource.USER)


def test_catalog_uses_project_user_builtin_precedence(tmp_path: Path) -> None:
    project, user, builtin = roots(tmp_path)
    write_definition(builtin / "same.md", name="same", description="builtin role")
    write_definition(user / "same.md", name="same", description="user role")
    write_definition(
        project / ".mewcode" / "agents" / "same.md",
        name="same",
        description="project role",
    )

    catalog = AgentCatalog.load(project, user, builtin)
    definition = catalog.resolve("SAME")

    assert definition is not None
    assert definition.description == "project role"
    assert definition.source is DefinitionSource.PROJECT


def test_catalog_ignores_plugin_placeholder_and_collects_user_diagnostics(
    tmp_path: Path,
) -> None:
    project, user, builtin = roots(tmp_path)
    write_definition(builtin / "builtin.md", name="builtin")
    write_definition(
        project / ".mewcode" / "plugins" / "agents" / "ignored.md",
        name="ignored",
    )
    (user / "invalid.md").parent.mkdir(parents=True, exist_ok=True)
    (user / "invalid.md").write_text("not a definition", encoding="utf-8")

    catalog = AgentCatalog.load(project, user, builtin)

    assert catalog.resolve("builtin") is not None
    assert catalog.resolve("ignored") is None
    assert len(catalog.diagnostics()) == 1


def test_catalog_rejects_invalid_builtin_as_program_error(tmp_path: Path) -> None:
    project, user, builtin = roots(tmp_path)
    (builtin / "invalid.md").parent.mkdir(parents=True)
    (builtin / "invalid.md").write_text("not a definition", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Agent"):
        AgentCatalog.load(project, user, builtin)


def test_builtin_definitions_and_prompt_listing_are_available(tmp_path: Path) -> None:
    project, user, _ = roots(tmp_path)
    catalog = AgentCatalog.load(project, user)

    assert [item.name for item in catalog.effective()] == [
        "explore",
        "general-purpose",
        "plan",
    ]
    assert "`explore`" in catalog.prompt_listing()
