from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "mewcode-http-test",
    host="127.0.0.1",
    port=int(os.environ["MCP_TEST_PORT"]),
)


@mcp.tool(annotations={"readOnlyHint": True})
def echo(value: str) -> str:
    return f"http:{value}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
