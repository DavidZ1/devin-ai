import json

from starrocks_mcp import server
from starrocks_mcp.config import Settings
from starrocks_mcp.results import TRUNCATION_NOTE


PLAN_TRUNCATION_NOTE = "... 执行计划已截断 / Plan truncated"


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.requested_size = None

    def execute(self, sql, _parameters=None):
        self.sql = sql

    def fetchmany(self, size):
        self.requested_size = size
        return self.rows[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor

    def cursor(self):
        return self.fake_cursor


class FakeConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args):
        return False


def stub_database_connection(monkeypatch, cursor):
    connection = FakeConnection(cursor)
    monkeypatch.setattr(
        server.db,
        "database_connection",
        lambda _settings: FakeConnectionContext(connection),
    )
    return connection


def test_explain_query_returns_complete_plan(monkeypatch):
    cursor = FakeCursor([("PLAN FRAGMENT 0",), ("  OLAP SCAN",)])
    stub_database_connection(monkeypatch, cursor)

    result = server._explain_query(
        "SELECT 1", None, Settings(max_rows=5, max_result_chars=1000)
    )

    assert result == "PLAN FRAGMENT 0\n  OLAP SCAN"
    assert cursor.requested_size == 6


def test_explain_query_truncates_extra_plan_lines(monkeypatch):
    cursor = FakeCursor([("line 1",), ("line 2",), ("line 3",)])
    stub_database_connection(monkeypatch, cursor)

    result = server._explain_query(
        "SELECT 1", None, Settings(max_rows=2, max_result_chars=1000)
    )

    assert result == f"line 1\nline 2\n{PLAN_TRUNCATION_NOTE}"
    assert cursor.requested_size == 3


def test_explain_query_truncates_plan_to_character_limit(monkeypatch):
    cursor = FakeCursor([("x" * 100,)])
    stub_database_connection(monkeypatch, cursor)

    result = server._explain_query(
        "SELECT 1", None, Settings(max_rows=5, max_result_chars=60)
    )

    assert len(result) <= 60
    assert result.endswith(PLAN_TRUNCATION_NOTE)


class DescribeCursor:
    def __init__(self):
        self.rows = []

    def execute(self, sql, _parameters=None):
        if "table_comment" in sql:
            self.rows = [("table comment",)]
        elif "column_name" in sql:
            self.rows = [("value", "VARCHAR", "YES", "", "")]
        else:
            self.rows = [("x" * 60_000,) for _ in range(3)]

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def fetchmany(self, size):
        rows, self.rows = self.rows[:size], self.rows[size:]
        return rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_describe_table_drops_sample_rows_to_fit_result_limit(monkeypatch):
    stub_database_connection(monkeypatch, DescribeCursor())
    settings = Settings(max_result_chars=50_000)

    result = server._describe_table("demo", "smoke_test", 3, settings)

    serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    assert len(serialized) <= settings.max_result_chars
    assert result["sample_rows"] == []
    assert result["sample_truncated"] is True
    assert result["note"] == TRUNCATION_NOTE
