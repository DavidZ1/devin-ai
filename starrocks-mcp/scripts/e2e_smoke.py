from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from fastmcp import Client
from fastmcp.client.transports.http import StreamableHttpTransport

MCP_URL = os.getenv("E2E_MCP_URL", "http://127.0.0.1:8000/mcp")
TOKEN = os.getenv("E2E_MCP_TOKEN", "xxx")
DATABASE = os.getenv("E2E_DATABASE", "demo")
TABLE = os.getenv("E2E_TABLE", "smoke_test")


def printable(result: Any) -> str:
    if hasattr(result, "model_dump"):
        return json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    return str(result)


async def main() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with Client(StreamableHttpTransport(MCP_URL, headers=headers)) as client:
        results = [
            ("list_databases", await client.call_tool("list_databases", {})),
            (
                "list_tables",
                await client.call_tool("list_tables", {"database": DATABASE}),
            ),
            (
                "describe_table",
                await client.call_tool(
                    "describe_table",
                    {"database": DATABASE, "table": TABLE, "sample_rows": 3},
                ),
            ),
            (
                "run_query",
                await client.call_tool(
                    "run_query",
                    {
                        "sql": f"SELECT * FROM `{DATABASE}`.`{TABLE}` ORDER BY id",
                        "database": DATABASE,
                    },
                ),
            ),
            (
                "explain_query",
                await client.call_tool(
                    "explain_query",
                    {
                        "sql": f"SELECT * FROM `{DATABASE}`.`{TABLE}`",
                        "database": DATABASE,
                    },
                ),
            ),
        ]
        for name, result in results:
            if getattr(result, "is_error", False):
                raise AssertionError(f"{name} returned an MCP error: {printable(result)}")
            print(f"{name}: {printable(result)[:500]}")

        large_sql = (
            f"SELECT a.id FROM `{DATABASE}`.`{TABLE}` AS a "
            f"CROSS JOIN `{DATABASE}`.`{TABLE}` AS b "
            f"CROSS JOIN `{DATABASE}`.`{TABLE}` AS c LIMIT 100000"
        )
        started = time.perf_counter()
        large_result = await client.call_tool(
            "run_query",
            {"sql": large_sql, "database": DATABASE, "max_rows": 10},
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        if getattr(large_result, "is_error", False):
            raise AssertionError(
                f"large-LIMIT run_query failed: {printable(large_result)}"
            )
        large_content = getattr(large_result, "structured_content", None)
        if not isinstance(large_content, dict):
            raise AssertionError(
                f"large-LIMIT run_query returned no structured content: "
                f"{printable(large_result)}"
            )
        if large_content.get("truncated") is not True:
            raise AssertionError(
                f"large-LIMIT query was not truncated: {printable(large_result)}"
            )
        print(
            "large-LIMIT run_query: "
            f"row_count={large_content.get('row_count')}, "
            f"truncated={large_content.get('truncated')}, "
            f"elapsed_ms={elapsed_ms:.2f}"
        )

        try:
            write_result = await client.call_tool(
                "run_query",
                {
                    "sql": f"INSERT INTO `{DATABASE}`.`{TABLE}` VALUES (999, 'blocked')",
                    "database": DATABASE,
                },
            )
        except Exception as exc:
            if "只读" not in str(exc) and "not allowed" not in str(exc):
                raise
            print(f"write rejection: {exc}")
        else:
            if not getattr(write_result, "is_error", False):
                raise AssertionError("write SQL was not rejected")
            print(f"write rejection: {printable(write_result)[:300]}")

    try:
        async with Client(StreamableHttpTransport(MCP_URL)) as unauthenticated:
            await unauthenticated.list_tools()
    except Exception as exc:
        print(f"no-token rejection: {type(exc).__name__}: {exc}")
    else:
        raise AssertionError("request without an API key unexpectedly succeeded")

    print("E2E smoke passed")


if __name__ == "__main__":
    asyncio.run(main())
