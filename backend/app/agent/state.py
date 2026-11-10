from typing import Any, NotRequired, TypedDict
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import User
from app.schemas.connections import SchemaInfo
from app.sql.schemas import SQLExecutionResponse, SQLGenerationResponse


class AssistantState(TypedDict):
    db: Session
    user: User
    conversation_id: UUID
    connection_id: UUID
    question: str
    conversation_context: list[dict[str, str]]
    intent: NotRequired[str]
    intent_message: NotRequired[str]
    schemas: NotRequired[list[SchemaInfo]]
    generation: NotRequired[SQLGenerationResponse]
    sql_query: NotRequired[str]
    validation_errors: NotRequired[list[str]]
    execution: NotRequired[SQLExecutionResponse]
    analysis: NotRequired[str]
    answer: NotRequired[str]
    workflow_status: NotRequired[str]
    workflow_error: NotRequired[str]
    database_dialect: NotRequired[str]
    steps: NotRequired[list[dict[str, str]]]
    response_metadata: NotRequired[dict[str, Any]]
