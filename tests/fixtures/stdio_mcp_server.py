from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mewcode-test")


@mcp.tool(annotations={"readOnlyHint": True})
def echo(value: str) -> str:
    return f"{os.environ.get('MCP_TEST_VALUE', '')}:{value}"


if __name__ == "__main__":
    mcp.run()
