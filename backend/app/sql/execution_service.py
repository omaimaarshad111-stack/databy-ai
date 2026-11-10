from collections import OrderedDict
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
import logging
import time
from threading import RLock
from uuid import UUID, uuid4

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database_targets.connection_manager import connection_manager
from app.database_targets.exceptions import (
    DatabaseTargetError,
)
from app.database_targets.schema_inspector import inspect_database_schema
from app.db.models import Conversation, QueryHistory, User
from app.services.connection_service import get_owned_connection
from app.sql.dialects import DatabaseDialect, get_sqlglot_dialect
from app.sql.execution_limits import (
    ExecutionLimits,
    TooManyConcurrentExecutionsError,
    user_execution_limiter,
)
from app.sql.executor import (
    QueryExecutionData,
    QueryExecutionError,
    QueryExecutionTimeoutError,
    execute_validated_sql,
)
from app.sql.schemas import (
    ExecutionStatus,
    SQLExecutionRequest,
    SQLExecutionResponse,
)
from app.sql.validator import validate_read_only_sql

logger = logging.getLogger(__name__)


class InvalidConversationError(Exception):
    pass


class ExecutionNotFoundError(Exception):
    pass


class ExecutionResultCache:
    def __init__(self) -> None:
        self._lock = RLock()
        self._entries: OrderedDict[
            UUID, tuple[UUID, float, int, SQLExecutionResponse]
        ] = OrderedDict()
        self._total_bytes = 0

    def _remove(self, execution_id: UUID) -> None:
        entry = self._entries.pop(execution_id, None)
        if entry is not None:
            self._total_bytes -= entry[2]

    def _purge_expired(self, now: float) -> None:
        expired = [
            execution_id
            for execution_id, (_, expires_at, _, _) in self._entries.items()
            if expires_at <= now
        ]
        for execution_id in expired:
            self._remove(execution_id)

    def put(
        self,
        user_id: UUID,
        response: SQLExecutionResponse,
        limits: ExecutionLimits,
    ) -> None:
        size = len(response.model_dump_json().encode("utf-8"))
        if size > limits.cache_max_bytes:
            return
        now = time.monotonic()
        with self._lock:
            self._purge_expired(now)
            self._remove(response.execution_id)
            while self._entries and (
                self._total_bytes + size > limits.cache_max_bytes
                or len(self._entries) >= limits.cache_max_entries
            ):
                oldest_id = next(iter(self._entries))
                self._remove(oldest_id)
            self._entries[response.execution_id] = (
                user_id,
                now + limits.cache_ttl_seconds,
                size,
                response,
            )
            self._total_bytes += size

    def get(self, user_id: UUID, execution_id: UUID) -> SQLExecutionResponse | None:
        with self._lock:
            self._purge_expired(time.monotonic())
            entry = self._entries.get(execution_id)
            if entry is None or entry[0] != user_id:
                return None
            self._entries.move_to_end(execution_id)
            return entry[3].model_copy(deep=True)


execution_result_cache = ExecutionResultCache()


def _redact_sql_literals_for_history(
    sql_query: str,
    dialect: DatabaseDialect,
) -> str:
    try:
        statements = sqlglot.parse(sql_query, read=get_sqlglot_dialect(dialect))
    except ParseError:
        return "[unparseable SQL omitted]"
    parsed = [statement for statement in statements if statement is not None]
    if not parsed:
        return "[unparseable SQL omitted]"
    for statement in parsed:
        for literal in list(statement.find_all(exp.Literal)):
            literal.replace(
                exp.Literal.string("[redacted]")
                if literal.is_string
                else exp.Literal.number("0")
            )
    return ";\n".join(
        statement.sql(dialect=get_sqlglot_dialect(dialect), comments=False)
        for statement in parsed
    )


@contextmanager
def _limited_execution(user_id: UUID, maximum: int) -> Generator[None, None, None]:
    user_execution_limiter.acquire(user_id, maximum)
    try:
        yield
    finally:
        user_execution_limiter.release(user_id)


def _completed_response(
    execution_id: UUID,
    status: ExecutionStatus,
    duration_ms: float,
    *,
    data: QueryExecutionData | None = None,
    error: str | None = None,
    validation_errors: list[str] | None = None,
    connection_id: UUID | None = None,
    created_at: datetime | None = None,
) -> SQLExecutionResponse:
    return SQLExecutionResponse(
        execution_id=execution_id,
        status=status,
        columns=data.columns if data else [],
        rows=data.rows if data else [],
        row_count=data.row_count if data else 0,
        execution_duration_ms=round(duration_ms, 3),
        truncated=data.truncated if data else False,
        error=error,
        validation_errors=validation_errors or [],
        connection_id=connection_id,
        created_at=created_at,
    )


def _finish_history(
    db: Session,
    history: QueryHistory,
    status: ExecutionStatus,
    duration_ms: float,
) -> None:
    history.execution_status = "succeeded" if status == "success" else "failed"
    history.execution_duration = duration_ms / 1000
    db.add(history)
    db.commit()
    db.refresh(history)


def execute_query(
    db: Session,
    user: User,
    connection_id: UUID,
    request: SQLExecutionRequest,
    *,
    natural_language_question: str = "Manual SQL execution",
) -> SQLExecutionResponse:
    connection = get_owned_connection(db, user, connection_id)
    limits = ExecutionLimits.from_settings()
    page_size = request.page_size or limits.default_page_size
    if page_size > limits.max_page_size:
        raise ValueError("Requested page size exceeds the configured maximum.")
    if request.offset > limits.max_offset:
        raise ValueError("Requested offset exceeds the configured maximum.")
    if len(request.sql_query) > get_settings().sql_max_query_chars:
        raise ValueError("SQL query exceeds the configured length limit.")

    if request.conversation_id is not None:
        conversation = db.scalar(
            select(Conversation.id).where(
                Conversation.id == request.conversation_id,
                Conversation.user_id == user.id,
            )
        )
        if conversation is None:
            raise InvalidConversationError

    dialect: DatabaseDialect = connection.database_type
    execution_id = uuid4()
    history = QueryHistory(
        id=execution_id,
        user_id=user.id,
        connection_id=connection.id,
        conversation_id=request.conversation_id,
        natural_language_question=natural_language_question[:4000],
        generated_sql=_redact_sql_literals_for_history(request.sql_query, dialect),
        execution_status="pending",
    )
    db.add(history)
    db.commit()
    started_at = time.monotonic()

    def complete(
        status: str,
        *,
        data: QueryExecutionData | None = None,
        error: str | None = None,
        validation_errors: list[str] | None = None,
    ) -> SQLExecutionResponse:
        duration_ms = (time.monotonic() - started_at) * 1000
        response = _completed_response(
            execution_id,
            status,
            duration_ms,
            data=data,
            error=error,
            validation_errors=validation_errors,
            connection_id=connection.id,
            created_at=history.created_at,
        )
        _finish_history(db, history, status, duration_ms)
        execution_result_cache.put(user.id, response, limits)
        return response

    try:
        schemas = inspect_database_schema(connection_manager.get_engine(connection))
        validation = validate_read_only_sql(
            request.sql_query,
            dialect,
            schemas,
        )
        if not validation.is_valid:
            return complete(
                "rejected",
                error="The SQL query failed read-only validation.",
                validation_errors=validation.validation_errors,
            )

        with _limited_execution(user.id, limits.max_concurrent_per_user):
            data = execute_validated_sql(
                connection_manager.get_engine(connection),
                dialect,
                request.sql_query,
                page_size,
                request.offset,
                limits,
            )
        return complete("success", data=data)
    except TooManyConcurrentExecutionsError:
        return complete(
            "busy",
            error="You already have the maximum number of concurrent queries running.",
        )
    except QueryExecutionTimeoutError:
        return complete(
            "timed_out",
            error="The query exceeded the configured execution time limit.",
        )
    except QueryExecutionError as exc:
        logger.warning("Read-only query execution failed (%s).", type(exc).__name__)
        return complete(
            "failed",
            error="The database could not complete this read-only query.",
        )
    except DatabaseTargetError as exc:
        logger.warning("Connected database operation failed (%s).", type(exc).__name__)
        return complete(
            "failed",
            error="The connected database is unavailable or could not complete the query.",
        )


def get_execution_result(
    db: Session,
    user: User,
    execution_id: UUID,
) -> SQLExecutionResponse:
    history = db.scalar(
        select(QueryHistory).where(
            QueryHistory.id == execution_id,
            QueryHistory.user_id == user.id,
        )
    )
    if history is None:
        raise ExecutionNotFoundError
    cached = execution_result_cache.get(user.id, execution_id)
    if cached is not None:
        return cached
    if history.execution_status == "pending":
        status: ExecutionStatus = "running"
        message = "Execution is still in progress."
    elif history.execution_status == "succeeded":
        status = "results_expired"
        message = "The result window expired; execution history metadata is retained."
    else:
        status = "results_expired"
        message = "The execution result is no longer available; history metadata is retained."
    duration_ms = (
        (history.execution_duration or 0) * 1000
        if history.execution_duration is not None
        else 0
    )
    return _completed_response(
        execution_id,
        status,
        duration_ms,
        error=message,
        connection_id=history.connection_id,
        created_at=history.created_at,
    )
