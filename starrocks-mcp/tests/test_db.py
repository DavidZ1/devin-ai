import pymysql

from starrocks_mcp import db
from starrocks_mcp.config import Settings


class FakeCursor:
    def __init__(self, connection, rows):
        self.connection = connection
        self.rows = rows
        self.position = 0
        self.description = [("value",)]
        self.fetch_sizes = []
        self.closed = False

    def execute(self, sql):
        self.sql = sql

    def fetchmany(self, size):
        self.fetch_sizes.append(size)
        rows = self.rows[self.position : self.position + size]
        self.position += len(rows)
        return rows

    def close(self):
        self.closed = True
        self.connection = None


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.open = True
        self.close_calls = 0
        self.force_close_calls = 0
        self.cursor_instance = None
        self.cursor_class = None

    def cursor(self, cursor_class=None):
        self.cursor_class = cursor_class
        self.cursor_instance = FakeCursor(self, self.rows)
        return self.cursor_instance

    def _force_close(self):
        self.force_close_calls += 1
        self.open = False

    def close(self):
        self.close_calls += 1
        self.open = False


def test_fetch_bounded_stops_after_extra_row_and_force_closes(monkeypatch):
    connection = FakeConnection([(1,), (2,), (3,), (4,), (5,)])
    monkeypatch.setattr(db, "connect", lambda _settings: connection)

    with db.database_connection(Settings()) as active_connection:
        columns, rows, more = db.fetch_bounded(
            active_connection, "SELECT value", limit=2
        )

    assert columns == ["value"]
    assert rows == [(1,), (2,), (3,)]
    assert more is True
    assert connection.cursor_class is pymysql.cursors.SSCursor
    assert connection.cursor_instance.fetch_sizes == [3]
    assert connection.cursor_instance.position == 3
    assert connection.force_close_calls == 1
    assert connection.close_calls == 0
    assert connection.cursor_instance.closed is False
    assert connection.cursor_instance.connection is None


def test_fetch_bounded_closes_normally_when_result_is_exhausted(monkeypatch):
    connection = FakeConnection([(1,), (2,)])
    monkeypatch.setattr(db, "connect", lambda _settings: connection)

    with db.database_connection(Settings()) as active_connection:
        columns, rows, more = db.fetch_bounded(
            active_connection, "SELECT value", limit=2
        )

    assert columns == ["value"]
    assert rows == [(1,), (2,)]
    assert more is False
    assert connection.cursor_class is pymysql.cursors.SSCursor
    assert connection.cursor_instance.fetch_sizes == [3]
    assert connection.cursor_instance.closed is True
    assert connection.force_close_calls == 0
    assert connection.close_calls == 1
