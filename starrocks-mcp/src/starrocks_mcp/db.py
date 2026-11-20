from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import pymysql

from .config import Settings

logger = logging.getLogger(__name__)


def connect(settings: Settings) -> pymysql.connections.Connection:
    options: dict[str, Any] = {
        "host": settings.starrocks_host,
        "port": settings.starrocks_port,
        "user": settings.starrocks_user,
        "password": settings.starrocks_password,
        "connect_timeout": 10,
        "read_timeout": settings.query_timeout_seconds + 5,
        "charset": "utf8mb4",
        "autocommit": True,
    }
    if settings.default_db:
        options["database"] = settings.default_db
    connection = pymysql.connect(**options)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SET query_timeout = {int(settings.query_timeout_seconds)}")
    except Exception:
        connection.close()
        raise
    return connection


@contextmanager
def database_connection(settings: Settings) -> Iterator[pymysql.connections.Connection]:
    connection = connect(settings)
    try:
        yield connection
    finally:
        if connection.open:
            connection.close()


def set_select_limit(connection: pymysql.connections.Connection, max_rows: int) -> None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"SET sql_select_limit = {int(max_rows) + 1}")
    except Exception as exc:
        logger.warning("Could not set StarRocks sql_select_limit: %s", exc)


def fetch_bounded(
    connection: pymysql.connections.Connection, sql: str, limit: int
) -> tuple[list[str], list[tuple[Any, ...]], bool]:
    cursor = connection.cursor(pymysql.cursors.SSCursor)
    close_cursor = True
    try:
        cursor.execute(sql)
        columns = [
            str(description[0]) for description in (cursor.description or ())
        ]
        rows = cursor.fetchmany(limit + 1)
        more = len(rows) > limit
        if more:
            force_close = getattr(connection, "_force_close", None)
            try:
                if callable(force_close):
                    force_close()
                else:
                    connection.close()
            finally:
                cursor.connection = None
                close_cursor = False
        return columns, rows[: limit + 1], more
    finally:
        if close_cursor:
            cursor.close()


def serialize_value(value: Any) -> Any:
    if isinstance(value, (Decimal, datetime, date, time, timedelta, bytes)):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def safe_database_error(error: Exception, settings: Settings) -> str:
    message = str(error)
    for sensitive in (settings.starrocks_password, settings.starrocks_host):
        if sensitive:
            message = message.replace(sensitive, "[redacted]")
    return f"StarRocks database error ({type(error).__name__}): {message}"
