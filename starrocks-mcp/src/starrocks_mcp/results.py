from __future__ import annotations

import json
from typing import Any, Iterable

from .db import serialize_value

TRUNCATION_NOTE = (
    "结果已截断，请添加 LIMIT 或在数据库侧聚合后重试 / "
    "Results were truncated; add LIMIT or aggregate in SQL."
)


def shape_result(
    columns: Iterable[str],
    rows: Iterable[Iterable[Any]],
    max_rows: int,
    max_result_chars: int,
) -> dict[str, Any]:
    all_rows = [[serialize_value(value) for value in row] for row in rows]
    truncated = len(all_rows) > max_rows
    result: dict[str, Any] = {
        "columns": list(columns),
        "rows": all_rows[:max_rows],
        "row_count": min(len(all_rows), max_rows),
        "truncated": truncated,
        "elapsed_ms": 0,
    }
    if truncated:
        result["note"] = TRUNCATION_NOTE
    if _serialized_length(result) > max_result_chars:
        result["truncated"] = True
        result["note"] = TRUNCATION_NOTE
        while result["rows"] and _serialized_length(result) > max_result_chars:
            result["rows"].pop()
        result["row_count"] = len(result["rows"])
    return result


def _serialized_length(value: dict[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
