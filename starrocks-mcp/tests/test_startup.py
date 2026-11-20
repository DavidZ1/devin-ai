import pytest

from starrocks_mcp.config import Settings
from starrocks_mcp.server import build_http_app


@pytest.mark.parametrize("transport", ["streamable-http", "sse"])
def test_http_startup_requires_api_keys(transport):
    settings = Settings(mcp_transport=transport)
    with pytest.raises(ValueError, match="requires MCP_API_KEYS"):
        build_http_app(settings)


def test_http_startup_can_explicitly_allow_no_auth():
    app = build_http_app(
        Settings(mcp_transport="streamable-http", allow_no_auth=True)
    )
    assert app is not None
