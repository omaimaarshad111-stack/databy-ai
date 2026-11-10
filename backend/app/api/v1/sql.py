from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.database_targets.exceptions import (
    ConnectionNotFoundError,
    DatabaseTargetError,
)
from app.db.models import User
from app.db.session import get_db
from app.schemas.connections import SchemaInfo
from app.sql.execution_service import (
    ExecutionNotFoundError,
    InvalidConversationError,
    execute_query,
    get_execution_result,
)
from app.services.connection_service import (
    get_owned_connection,
    inspect_connection_schema,
)
from app.sql.dialects import DatabaseDialect
from app.sql.exceptions import GroqProviderError, MissingGroqAPIKeyError
from app.sql.generator import generate_sql
from app.sql.schemas import (
    SQLGenerationRequest,
    SQLGenerationResponse,
    SQLExecutionRequest,
    SQLExecutionResponse,
    SQLValidationRequest,
    SQLValidationResponse,
)
from app.sql.validator import validate_read_only_sql

router = APIRouter(tags=["SQL generation and validation"])


def _owned_schema(
    db: Session,
    user: User,
    connection_id: UUID,
) -> tuple[DatabaseDialect, list[SchemaInfo]]:
    try:
        connection = get_owned_connection(db, user, connection_id)
        schemas = inspect_connection_schema(connection)
    except ConnectionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database connection not found.",
        ) from None
    except (DatabaseTargetError, KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The database schema could not be inspected.",
        ) from None
    return connection.database_type, schemas


@router.post(
    "/connections/{connection_id}/generate-sql",
    response_model=SQLGenerationResponse,
)
def generate_sql_for_connection(
    connection_id: UUID,
    request: SQLGenerationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SQLGenerationResponse:
    dialect, schemas = _owned_schema(db, current_user, connection_id)
    try:
        return generate_sql(request.question, dialect, schemas)
    except MissingGroqAPIKeyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SQL generation is not configured. Set GROQ_API_KEY.",
        ) from None
    except GroqProviderError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The SQL generation provider is temporarily unavailable.",
        ) from None


@router.post("/sql/validate", response_model=SQLValidationResponse)
def validate_sql_for_connection(
    request: SQLValidationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SQLValidationResponse:
    dialect, schemas = _owned_schema(db, current_user, request.connection_id)
    if len(request.sql_query) > get_settings().sql_max_query_chars:
        return SQLValidationResponse(
            is_valid=False,
            database_dialect=dialect,
            query_type=None,
            validation_errors=["The SQL query exceeds the configured length limit."],
            tables_used=[],
        )
    return validate_read_only_sql(request.sql_query, dialect, schemas)


@router.post(
    "/connections/{connection_id}/execute",
    response_model=SQLExecutionResponse,
)
def execute_sql_for_connection(
    connection_id: UUID,
    request: SQLExecutionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SQLExecutionResponse:
    settings = get_settings()
    if request.page_size is not None and request.page_size > settings.sql_execution_max_page_size:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Requested page size exceeds the configured maximum.",
        )
    if request.offset > settings.sql_execution_max_offset:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Requested offset exceeds the configured maximum.",
        )
    try:
        return execute_query(db, current_user, connection_id, request)
    except ConnectionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database connection not found.",
        ) from None
    except InvalidConversationError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from None


@router.get(
    "/executions/{execution_id}",
    response_model=SQLExecutionResponse,
)
def get_sql_execution(
    execution_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SQLExecutionResponse:
    try:
        return get_execution_result(db, current_user, execution_id)
    except ExecutionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found.",
        ) from None
