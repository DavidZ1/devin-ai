from __future__ import annotations

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from .config import SYSTEM_DATABASES


class SqlRejected(ValueError):
    """Raised when a query cannot be proven read-only and in-scope."""


_FORBIDDEN_NODE_NAMES = {
    "Alter",
    "Analyze",
    "Attach",
    "Cache",
    "Call",
    "Command",
    "Commit",
    "Copy",
    "Create",
    "Deallocate",
    "Delete",
    "Detach",
    "Drop",
    "Execute",
    "Export",
    "Grant",
    "Insert",
    "Into",
    "Kill",
    "LoadData",
    "Merge",
    "Optimize",
    "Prepare",
    "Pragma",
    "Refresh",
    "Revoke",
    "Rollback",
    "Set",
    "Transaction",
    "Truncate",
    "TruncateTable",
    "Update",
    "Use",
}
_FORBIDDEN_TYPES = tuple(
    node_type
    for name in _FORBIDDEN_NODE_NAMES
    if isinstance((node_type := getattr(exp, name, None)), type)
)


def validate_select(
    sql: str,
    default_db: str | None = None,
    allowed_dbs: frozenset[str] | set[str] | None = None,
    database: str | None = None,
) -> exp.Query:
    """Parse and validate a single read-only query without rewriting it."""
    try:
        statements = [statement for statement in parse(sql, dialect="starrocks") if statement]
    except (ParseError, ValueError) as exc:
        raise SqlRejected("SQL 无法解析 / Could not parse SQL.") from exc
    if len(statements) != 1:
        raise SqlRejected("仅允许一条 SQL / Exactly one SQL statement is allowed.")
    query = statements[0]
    if not isinstance(query, exp.Query):
        raise SqlRejected("仅允许只读查询 / Only read-only queries are allowed.")
    for node in query.walk():
        if isinstance(node, _FORBIDDEN_TYPES):
            raise SqlRejected("检测到写入或管理操作 / Write or admin SQL is not allowed.")
        if isinstance(node, (exp.DDL, exp.DML)):
            raise SqlRejected("仅允许只读查询 / Only read-only queries are allowed.")

    allowed = {name.casefold() for name in (allowed_dbs or set())}
    cte_names = {
        cte.alias_or_name.casefold()
        for cte in query.find_all(exp.CTE)
        if cte.alias_or_name
    }
    effective_database = database or default_db
    for table in query.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SqlRejected("不允许表函数 / Table functions are not allowed.")
        catalog = table.catalog
        if catalog and catalog.casefold() != "default_catalog":
            raise SqlRejected(
                "不允许外部 catalog / External catalogs are not allowed."
            )
        if (
            not table.db
            and not catalog
            and table.name
            and table.name.casefold() in cte_names
        ):
            continue
        table_database = table.db or effective_database
        if not table_database:
            if allowed:
                raise SqlRejected(
                    "请为表指定数据库 / Qualify tables when a database allowlist is set."
                )
            continue
        normalized = table_database.casefold()
        if normalized in SYSTEM_DATABASES and normalized not in allowed:
            raise SqlRejected(
                f"系统数据库不可访问 / System database is blocked: {table_database}."
            )
        if allowed and normalized not in allowed:
            raise SqlRejected(
                f"数据库不在允许列表中 / Database is not allowed: {table_database}."
            )
    return query
