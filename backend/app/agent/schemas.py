from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.sql.schemas import SQLExecutionResponse


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="New conversation", min_length=1, max_length=240)


class AssistantMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    content: str = Field(min_length=3, max_length=2000)


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime


class ConversationDetailResponse(ConversationResponse):
    messages: list[ConversationMessageResponse]


class AssistantCompletion(BaseModel):
    conversation_id: UUID
    message: ConversationMessageResponse
    intent: str | None = None
    steps: list[dict[str, str]]
    generated_sql: str | None = None
    validation_status: Literal["valid", "invalid", "not_run"]
    validation_errors: list[str] = Field(default_factory=list)
    execution: SQLExecutionResponse | None = None
    workflow_status: Literal["completed", "failed"]
