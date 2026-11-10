from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import get_settings


class QueryHistoryItem(BaseModel):
    id: UUID
    connection_id: UUID
    connection_name: str
    database_type: Literal["sqlite", "postgresql"]
    conversation_id: UUID | None
    natural_language_question: str
    generated_sql: str | None
    execution_status: Literal["pending", "succeeded", "failed", "cancelled"]
    execution_duration_ms: float | None
    created_at: datetime


class QueryHistoryPage(BaseModel):
    items: list[QueryHistoryItem]
    total: int
    page: int
    page_size: int


class SavedQueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    sql_query: str = Field(min_length=1)

    @field_validator("name", "sql_query")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field must not be blank.")
        return normalized

    @field_validator("sql_query")
    @classmethod
    def enforce_query_limit(cls, value: str) -> str:
        if len(value) > get_settings().sql_max_query_chars:
            raise ValueError("SQL query exceeds the configured length limit.")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class SavedQueryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    sql_query: str | None = Field(default=None, min_length=1)

    @field_validator("name", "sql_query")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field must not be blank.")
        return normalized

    @field_validator("sql_query")
    @classmethod
    def enforce_query_limit(cls, value: str | None) -> str | None:
        if value is not None and len(value) > get_settings().sql_max_query_chars:
            raise ValueError("SQL query exceeds the configured length limit.")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class SavedQueryResponse(BaseModel):
    id: UUID
    connection_id: UUID
    connection_name: str
    database_type: Literal["sqlite", "postgresql"]
    name: str
    description: str | None
    sql_query: str
    created_at: datetime
    updated_at: datetime
