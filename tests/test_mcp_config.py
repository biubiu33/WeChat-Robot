from __future__ import annotations

from pathlib import Path

import pytest

from mewcode.mcp.config import load_config


def write_mcp(home: Path, content: str) -> Path:
    path = home / ".mewcode" / "mcp.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_or_empty_config_returns_no_servers(tmp_path: Path) -> None:
    assert load_config(home=tmp_path).servers == {}
    write_mcp(tmp_path, "mcp_servers: {}\n")
    assert load_config(home=tmp_path).servers == {}


def test_valid_stdio_and_http_config_expands_only_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MCP_TOKEN", "secret")
    write_mcp(
        tmp_path,
        """
mcp_servers:
  local:
    type: stdio
    command: "node-${MCP_TOKEN}"
    args: ["server-${MCP_TOKEN}"]
    env:
      TOKEN: "${MCP_TOKEN}"
  remote:
    type: http
    url: https://example.test/mcp
    headers:
      Authorization: "Bearer ${MCP_TOKEN}"
""",
    )

    config = load_config(home=tmp_path)

    assert config.servers["local"].command == "node-${MCP_TOKEN}"
    assert config.servers["local"].args == ["server-${MCP_TOKEN}"]
    assert config.servers["local"].env == {"TOKEN": "secret"}
    assert config.servers["remote"].headers == {"Authorization": "Bearer secret"}


def test_undefined_variable_expands_empty_and_warns_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_mcp(
        tmp_path,
        """
mcp_servers:
  remote:
    type: http
    url: https://example.test/mcp
    headers:
      One: ${MISSING}
      Two: ${MISSING}
""",
    )

    config = load_config(home=tmp_path)

    assert config.servers["remote"].headers == {"One": "", "Two": ""}
    assert capsys.readouterr().err.count("${MISSING}") == 1


@pytest.mark.parametrize(
    "body",
    [
        "mcp_servers: []\n",
        "mcp_servers:\n  bad: {type: other}\n",
        "mcp_servers:\n  bad: {type: stdio}\n",
        "mcp_servers:\n  bad: {type: http}\n",
        "mcp_servers:\n  bad: {type: stdio, command: run, args: [1]}\n",
        "mcp_servers:\n  bad: {type: http, url: x, headers: {X: 1}}\n",
    ],
)
def test_invalid_server_config_is_skipped(
    tmp_path: Path, body: str, capsys: pytest.CaptureFixture[str]
) -> None:
    write_mcp(tmp_path, body)

    config = load_config(home=tmp_path)

    assert config.servers == {}
    assert "[mcp] warn:" in capsys.readouterr().err


def test_invalid_yaml_degrades_without_leaking_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_mcp(tmp_path, "mcp_servers: [not: valid\napi_key: secret")

    config = load_config(home=tmp_path)

    assert config.servers == {}
    error = capsys.readouterr().err
    assert "[mcp] warn:" in error
    assert "secret" not in error
