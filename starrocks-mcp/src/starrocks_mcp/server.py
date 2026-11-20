from __future__ import annotations

import logging
import time
from typing import Any

import anyio
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import db
from .audit import record_event
from .auth import AuthMiddleware, AuthenticationError, resolve_caller
from .config import Settings, database_is_allowed
from .results import shape_result
from .sql_guard import SqlRejected, validate_select

logger = logging.getLogger(__name__)
mcp = FastMCP("starrocks-mcp")
SETTINGS = Settings.from_env()


def _caller(settings: Settings) -> dict[str, str]:
    if settings.mcp_transport == "stdio":
        return {"key": "stdio"}
    if settings.allow_no_auth and not settings.api_keys:
        return {"key": "unauthenticated"}
    try:
        headers = get_http_headers(include={"authorization", "x-aily-jwt"})
        return resolve_caller(headers, settings)
    except (RuntimeError, LookupError):
        return {"key": "stdio"}
    except AuthenticationError:
        return {"key": "unknown"}


def _ensure_database_allowed(database: str, settings: Settings) -> None:
    if not database_is_allowed(database, settings.allowed_databases):
        raise SqlRejected(
            f"数据库不可访问 / Database is not allowed: {database}."
        )


def _safe_error(exc: Exception, settings: Settings) -> str:
    if isinstance(exc, SqlRejected):
        return str(exc)
    return db.safe_database_error(exc, settings)


def _run_audited(
    settings: Settings,
    tool: str,
    operation: Any,
    *,
    database: str | None = None,
    sql: str | None = None,
) -> Any:
    started = time.perf_counter()
    status = "ok"
    error_message: str | None = None
    row_count: int | None = None
    truncated: bool | None = None
    try:
        result = operation()
        if isinstance(result, list):
            row_count = len(result)
        elif isinstance(result, dict):
            row_count = result.get("row_count")
            if row_count is None and isinstance(result.get("sample_rows"), list):
                row_count = len(result["sample_rows"])
            truncated = result.get("truncated")
        return result
    except SqlRejected as exc:
        status = "rejected"
        error_message = str(exc)
        raise ToolError(error_message) from exc
    except Exception as exc:
        status = "error"
        error_message = _safe_error(exc, settings)
        raise ToolError(error_message) from exc
    finally:
        record_event(
            settings,
            caller=_caller(settings),
            tool=tool,
            database=database,
            sql=sql,
            row_count=row_count,
            truncated=truncated,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            status=status,
            error=error_message,
        )


def _list_databases(settings: Settings) -> list[str]:
    with db.database_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SHOW DATABASES")
            databases = [str(row[0]) for row in cursor.fetchall()]
    return [
        name
        for name in databases
        if database_is_allowed(name, settings.allowed_databases)
    ]


def _list_tables(database: str, settings: Settings) -> list[dict[str, Any]]:
    _ensure_database_allowed(database, settings)
    with db.database_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, table_type, table_comment "
                "FROM information_schema.tables "
                "WHERE table_schema = %s ORDER BY table_name",
                (database,),
            )
            rows = cursor.fetchall()
    return [
        {"name": row[0], "type": row[1], "comment": row[2]}
        for row in rows
    ]


def _describe_table(
    database: str, table: str, sample_rows: int, settings: Settings
) -> dict[str, Any]:
    _ensure_database_allowed(database, settings)
    sample_rows = max(0, min(int(sample_rows), 10))
    with db.database_connection(settings) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_comment FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = %s LIMIT 1",
                (database, table),
            )
            table_row = cursor.fetchone()
            if table_row is None:
                raise SqlRejected(
                    f"表不存在或不可见 / Table does not exist or is not visible: "
                    f"{database}.{table}."
                )
            cursor.execute(
                "SELECT column_name, data_type, is_nullable, column_key, "
                "column_comment FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position",
                (database, table),
            )
            columns = [
                {
                    "name": row[0],
                    "type": row[1],
                    "nullable": row[2],
                    "key": row[3],
                    "comment": row[4],
                }
                for row in cursor.fetchall()
            ]
            sample: list[list[Any]] = []
            if sample_rows:
                statement = (
                    f"SELECT * FROM {db.quote_identifier(database)}."
                    f"{db.quote_identifier(table)} LIMIT {sample_rows}"
                )
                cursor.execute(statement)
                sample = [
                    [db.serialize_value(value) for value in row]
                    for row in cursor.fetchmany(sample_rows)
                ]
    return {
        "database": database,
        "table": table,
        "comment": table_row[0],
        "columns": columns,
        "sample_rows": sample,
    }


def _use_database(connection: Any, database: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"USE {db.quote_identifier(database)}")


def _run_query(
    sql: str, database: str | None, max_rows: int | None, settings: Settings
) -> dict[str, Any]:
    validate_select(
        sql,
        default_db=settings.default_db,
        allowed_dbs=settings.allowed_databases,
        database=database,
    )
    if database:
        _ensure_database_allowed(database, settings)
    effective_max_rows = max(1, min(max_rows or settings.max_rows, settings.max_rows))
    started = time.perf_counter()
    with db.database_connection(settings) as connection:
        if database:
            _use_database(connection, database)
        db.set_select_limit(connection, effective_max_rows)
        with connection.cursor() as cursor:
            cursor.execute(sql)
            columns = [str(description[0]) for description in (cursor.description or ())]
            rows = cursor.fetchmany(effective_max_rows + 1)
    result = shape_result(
        columns,
        rows,
        max_rows=effective_max_rows,
        max_result_chars=settings.max_result_chars,
    )
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return result


def _explain_query(sql: str, database: str | None, settings: Settings) -> str:
    validate_select(
        sql,
        default_db=settings.default_db,
        allowed_dbs=settings.allowed_databases,
        database=database,
    )
    if database:
        _ensure_database_allowed(database, settings)
    with db.database_connection(settings) as connection:
        if database:
            _use_database(connection, database)
        with connection.cursor() as cursor:
            cursor.execute(f"EXPLAIN {sql}")
            rows = cursor.fetchmany(settings.max_rows + 1)
    return "\n".join("\t".join(str(value) for value in row) for row in rows)


@mcp.tool(description="列出当前账号可访问的数据库；系统数据库默认隐藏。")
async def list_databases() -> list[str]:
    settings = SETTINGS
    return await anyio.to_thread.run_sync(
        lambda: _run_audited(
            settings, "list_databases", lambda: _list_databases(settings)
        )
    )


@mcp.tool(description="列出指定数据库中的表及表类型、注释。")
async def list_tables(database: str) -> list[dict[str, Any]]:
    settings = SETTINGS
    return await anyio.to_thread.run_sync(
        lambda: _run_audited(
            settings,
            "list_tables",
            lambda: _list_tables(database, settings),
            database=database,
        )
    )


@mcp.tool(description="查看表注释、字段定义和最多 10 行样例；仅访问允许的数据库。")
async def describe_table(
    database: str, table: str, sample_rows: int = 3
) -> dict[str, Any]:
    settings = SETTINGS
    return await anyio.to_thread.run_sync(
        lambda: _run_audited(
            settings,
            "describe_table",
            lambda: _describe_table(database, table, sample_rows, settings),
            database=database,
        )
    )


@mcp.tool(
    description=(
        "运行只读 SELECT 查询（支持 CTE、UNION 等），可选 database 和结果行数上限。"
        "拒绝写入/管理 SQL；超过输出上限时请聚合或添加 LIMIT。"
    )
)
async def run_query(
    sql: str, database: str | None = None, max_rows: int | None = None
) -> dict[str, Any]:
    settings = SETTINGS
    return await anyio.to_thread.run_sync(
        lambda: _run_audited(
            settings,
            "run_query",
            lambda: _run_query(sql, database, max_rows, settings),
            database=database or settings.default_db,
            sql=sql,
        )
    )


@mcp.tool(description="对只读 SELECT 查询生成 StarRocks EXPLAIN 执行计划，不执行查询。")
async def explain_query(sql: str, database: str | None = None) -> str:
    settings = SETTINGS
    return await anyio.to_thread.run_sync(
        lambda: _run_audited(
            settings,
            "explain_query",
            lambda: _explain_query(sql, database, settings),
            database=database or settings.default_db,
            sql=sql,
        )
    )


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_http_app(settings: Settings):
    global SETTINGS
    if not settings.api_keys and not settings.allow_no_auth:
        raise ValueError(
            "HTTP transport requires MCP_API_KEYS unless MCP_ALLOW_NO_AUTH=true"
        )
    SETTINGS = settings
    return mcp.http_app(
        transport=settings.mcp_transport,
        path="/mcp",
        middleware=[Middleware(AuthMiddleware, settings=settings)],
    )
