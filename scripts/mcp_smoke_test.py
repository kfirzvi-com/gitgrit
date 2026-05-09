"""Post-deploy smoke test for the MCP server.

Usage:
    MCP_URL=https://gitgrit.dev/mcp/ MCP_TOKEN=grit_... uv run python scripts/mcp_smoke_test.py

Exit codes: 0 = pass, 1 = fail.
"""
import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def main() -> int:
    url = os.environ.get("MCP_URL")
    token = os.environ.get("MCP_TOKEN")
    if not url or not token:
        print("ERROR: MCP_URL and MCP_TOKEN environment variables are required")
        return 1

    print(f"Connecting to {url} ...")
    try:
        async with streamablehttp_client(
            url, headers={"Authorization": f"Bearer {token}"}
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("  [OK] initialize")

                await session.call_tool("list_policies", {})
                print("  [OK] list_policies")

                await session.call_tool("get_project_context_api", {})
                print("  [OK] get_project_context_api")

    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
