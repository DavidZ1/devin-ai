from __future__ import annotations

import argparse
from dataclasses import replace

def main() -> None:
    from . import server

    parser = argparse.ArgumentParser(description="Read-only StarRocks MCP server")
    parser.add_argument(
        "--transport", choices=("stdio", "streamable-http", "sse"), default=None
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    settings = server.SETTINGS
    settings = replace(
        settings,
        mcp_transport=args.transport or settings.mcp_transport,
        mcp_host=args.host or settings.mcp_host,
        mcp_port=args.port or settings.mcp_port,
    )
    server.SETTINGS = settings
    if settings.mcp_transport == "stdio":
        server.mcp.run(transport="stdio")
        return

    import uvicorn

    app = server.build_http_app(settings)
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
