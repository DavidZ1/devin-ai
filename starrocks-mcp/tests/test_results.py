from datetime import date, datetime, time, timedelta
from decimal import Decimal

from starrocks_mcp.db import serialize_value
from starrocks_mcp.results import TRUNCATION_NOTE, shape_result


def test_values_are_json_safe():
    values = [
        Decimal("1.25"),
        datetime(2024, 1, 2, 3, 4),
        date(2024, 1, 2),
        time(3, 4),
        timedelta(seconds=5),
        b"bytes",
    ]
    assert [serialize_value(value) for value in values] == [
        "1.25",
        "2024-01-02 03:04:00",
        "2024-01-02",
        "03:04:00",
        "0:00:05",
        "b'bytes'",
    ]


def test_row_limit_sets_truncation_flag():
    result = shape_result(["n"], [[1], [2], [3]], max_rows=2, max_result_chars=500)
    assert result["rows"] == [[1], [2]]
    assert result["row_count"] == 2
    assert result["truncated"] is True
    assert result["note"] == TRUNCATION_NOTE


def test_fetching_more_than_the_row_limit_sets_truncation_flag():
    result = shape_result(
        ["n"],
        [[1], [2]],
        max_rows=2,
        max_result_chars=500,
        more_rows=True,
    )
    assert result["rows"] == [[1], [2]]
    assert result["row_count"] == 2
    assert result["truncated"] is True
    assert result["note"] == TRUNCATION_NOTE


def test_character_limit_drops_rows_and_adds_note():
    result = shape_result(
        ["value"],
        [["x" * 80], ["y" * 80]],
        max_rows=10,
        max_result_chars=100,
    )
    assert result["rows"] == []
    assert result["row_count"] == 0
    assert result["truncated"] is True
    assert result["note"] == TRUNCATION_NOTE
