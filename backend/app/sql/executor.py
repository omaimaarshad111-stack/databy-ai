from dataclasses import dataclass
import time
from typing import Any

import sqlglot
from sqlglot import exp
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.sql.dialects import DatabaseDialect, get_sqlglot_dialect
from app.sql.execution_limits import ExecutionLimits
from app.sql.result_formatter import encode_json_size, result_columns, serialize_value
from app.sql.schemas import ExecutionColumn


class QueryExecutionTimeoutError(Exception):
    pass


class QueryExecutionError(Exception):
    pass


@dataclass(frozen=True)
class QueryExecutionData:
    columns: list[ExecutionColumn]
    rows: list[list[object | None]]
    row_count: int
    truncated: bool


def _bounded_query(
    sql_query: str,
    dialect: DatabaseDialect,
    page_size: int,
    offset: int,
) -> str:
    parsed = sqlglot.parse_one(sql_query, read=get_sqlglot_dialect(dialect))
    while isinstance(parsed, exp.Subquery):
        parsed = parsed.this

    existing_limit = parsed.args.get("limit")
    limit_value = page_size + offset + 1
    if existing_limit is not None:
        limit_expression = existing_limit.args.get("expression")
        limit_text = (
            limit_expression.this
            if isinstance(limit_expression, exp.Literal)
            and not limit_expression.is_string
            else None
        )
        if (
            existing_limit.args.get("limit_options") is not None
            or not isinstance(limit_text, str)
            or not limit_text.isdecimal()
        ):
            raise QueryExecutionError("The query uses an unsupported result limit.")
        limit_value = min(limit_value, int(limit_text))

    existing_offset = parsed.args.get("offset")
    offset_value = offset
    if existing_offset is not None:
        offset_expression = existing_offset.args.get("expression")
        offset_text = (
            offset_expression.this
            if isinstance(offset_expression, exp.Literal)
            and not offset_expression.is_string
            else None
        )
        if not isinstance(offset_text, str) or not offset_text.isdecimal():
            raise QueryExecutionError("The query uses an unsupported result offset.")
        offset_value += int(offset_text)

    parsed.set("limit", exp.Limit(expression=exp.Literal.number(str(limit_value))))
    parsed.set("offset", exp.Offset(expression=exp.Literal.number(str(offset_value))))
    return parsed.sql(dialect=get_sqlglot_dialect(dialect))


def _postgres_timeout(error: DBAPIError) -> bool:
    original = error.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return sqlstate == "57014"


def _collect_result(
    result: Any,
    limits: ExecutionLimits,
    page_size: int,
) -> QueryExecutionData:
    try:
        columns = result_columns(result)
        if len(columns) > limits.max_columns:
            raise QueryExecutionError("The query result exceeds the column limit.")

        header_size = encode_json_size([column.model_dump() for column in columns])
        response_reserve = 512
        if header_size + response_reserve > limits.max_result_bytes:
            raise QueryExecutionError("The query result metadata exceeds the response limit.")

        rows: list[list[object | None]] = []
        serialized_size = header_size
        row_budget = limits.max_result_bytes - response_reserve
        truncated = False

        while True:
            batch = result.fetchmany(min(64, page_size + 1 - len(rows)))
            if not batch:
                break
            for raw_row in batch:
                if len(rows) >= page_size:
                    truncated = True
                    break
                row = [serialize_value(value) for value in raw_row]
                row_size = encode_json_size(row) + 1
                if serialized_size + row_size > row_budget:
                    truncated = True
                    break
                rows.append(row)
                serialized_size += row_size
            if truncated:
                break
            if len(batch) < 64:
                break

        return QueryExecutionData(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
        )
    finally:
        result.close()


def execute_validated_sql(
    engine: Engine,
    database_dialect: DatabaseDialect,
    sql_query: str,
    page_size: int,
    offset: int,
    limits: ExecutionLimits,
) -> QueryExecutionData:
    bounded_sql = _bounded_query(sql_query, database_dialect, page_size, offset)
    deadline = time.monotonic() + limits.timeout_seconds

    try:
        if database_dialect == "sqlite":
            with engine.connect() as connection:
                raw_connection = connection.connection.driver_connection
                raw_connection.set_progress_handler(
                    lambda: int(time.monotonic() >= deadline),
                    1000,
                )
                try:
                    result = connection.execute(text(bounded_sql))
                    return _collect_result(result, limits, page_size)
                except SQLAlchemyError as exc:
                    if "interrupted" in str(exc).casefold() or time.monotonic() >= deadline:
                        raise QueryExecutionTimeoutError from None
                    raise QueryExecutionError from None
                finally:
                    raw_connection.set_progress_handler(None, 0)

        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                timeout_ms = max(1, int(limits.timeout_seconds * 1000))
                connection.exec_driver_sql(
                    f"SET LOCAL statement_timeout = '{timeout_ms}ms'"
                )
                streaming_connection = connection.execution_options(stream_results=True)
                result = streaming_connection.execute(text(bounded_sql))
                return _collect_result(result, limits, page_size)
            except DBAPIError as exc:
                if _postgres_timeout(exc) or time.monotonic() >= deadline:
                    raise QueryExecutionTimeoutError from None
                raise QueryExecutionError from None
            except SQLAlchemyError:
                raise QueryExecutionError from None
            finally:
                if transaction.is_active:
                    transaction.rollback()
    except (QueryExecutionError, QueryExecutionTimeoutError):
        raise
    except (SQLAlchemyError, OSError, ValueError, TypeError):
        if time.monotonic() >= deadline:
            raise QueryExecutionTimeoutError from None
        raise QueryExecutionError from None
