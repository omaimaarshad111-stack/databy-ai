import base64
import json
import math
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.engine import CursorResult

from app.sql.schemas import ExecutionColumn


def _unique_column_names(names: list[str]) -> list[str]:
    unique_names: list[str] = []
    used: set[str] = set()
    for index, name in enumerate(names, start=1):
        base_name = name or f"column_{index}"
        candidate = base_name
        suffix = 2
        while candidate in used:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        used.add(candidate)
        unique_names.append(candidate)
    return unique_names


def serialize_value(value: Any) -> object | None:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return str(value)


def result_columns(result: CursorResult[Any]) -> list[ExecutionColumn]:
    cursor = getattr(result, "cursor", None)
    description = cursor.description if cursor is not None else None
    raw_names = (
        [column[0] for column in description]
        if description
        else list(result.keys())
    )
    names = _unique_column_names([str(name) for name in raw_names])
    return [ExecutionColumn(name=name) for name in names]


def encode_json_size(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )
