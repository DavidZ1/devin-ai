from __future__ import annotations

import os
from dataclasses import dataclass

SYSTEM_DATABASES = frozenset(
    {"information_schema", "_statistics_", "sys", "starrocks_audit_db__"}
)


@dataclass(frozen=True)
class ApiKey:
    name: str
    token: str


@dataclass(frozen=True)
class Settings:
    starrocks_host: str = "localhost"
    starrocks_port: int = 9030
    starrocks_user: str = "root"
    starrocks_password: str = ""
    default_db: str | None = None
    allowed_databases: frozenset[str] = frozenset()
    query_timeout_seconds: int = 30
    max_rows: int = 500
    max_result_chars: int = 50_000
    mcp_transport: str = "stdio"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    api_keys: tuple[ApiKey, ...] = ()
    allow_no_auth: bool = False
    aily_jwt_secret: str | None = None
    aily_jwt_required: bool = False
    audit_log_file: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        allowed_databases = frozenset(
            name.strip().casefold()
            for name in os.getenv("STARROCKS_ALLOWED_DATABASES", "").split(",")
            if name.strip()
        )
        api_keys = tuple(
            ApiKey(name.strip(), token.strip())
            for item in os.getenv("MCP_API_KEYS", "").split(",")
            if item.strip()
            for name, separator, token in [item.partition("=")]
            if separator and name.strip() and token.strip()
        )
        transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
        if transport not in {"stdio", "streamable-http", "sse"}:
            raise ValueError(
                "MCP_TRANSPORT must be stdio, streamable-http, or sse"
            )
        jwt_secret = os.getenv("AILY_JWT_SECRET") or None
        jwt_required = _read_bool("AILY_JWT_REQUIRED", False)
        if jwt_required and not jwt_secret:
            raise ValueError("AILY_JWT_REQUIRED needs AILY_JWT_SECRET")
        return cls(
            starrocks_host=os.getenv("STARROCKS_HOST", "localhost"),
            starrocks_port=int(os.getenv("STARROCKS_PORT", "9030")),
            starrocks_user=os.getenv("STARROCKS_USER", "root"),
            starrocks_password=os.getenv("STARROCKS_PASSWORD", ""),
            default_db=os.getenv("STARROCKS_DEFAULT_DB") or None,
            allowed_databases=allowed_databases,
            query_timeout_seconds=int(os.getenv("QUERY_TIMEOUT_SECONDS", "30")),
            max_rows=int(os.getenv("MAX_ROWS", "500")),
            max_result_chars=int(os.getenv("MAX_RESULT_CHARS", "50000")),
            mcp_transport=transport,
            mcp_host=os.getenv("MCP_HOST", "0.0.0.0"),
            mcp_port=int(os.getenv("MCP_PORT", "8000")),
            api_keys=api_keys,
            allow_no_auth=_read_bool("MCP_ALLOW_NO_AUTH", False),
            aily_jwt_secret=jwt_secret,
            aily_jwt_required=jwt_required,
            audit_log_file=os.getenv("AUDIT_LOG_FILE") or None,
        )


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().casefold()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def database_is_allowed(database: str, allowed_databases: frozenset[str]) -> bool:
    normalized = database.casefold()
    if normalized in SYSTEM_DATABASES and normalized not in allowed_databases:
        return False
    return not allowed_databases or normalized in allowed_databases
