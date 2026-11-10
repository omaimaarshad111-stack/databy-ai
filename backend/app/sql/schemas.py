from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ExecutionStatus = Literal[
    "success",
    "failed",
    "timed_out",
    "rejected",
    "busy",
    "running",
    "results_expired",
]
GenerationStatus = Literal[
    "success",
    "needs_clarification",
    "unsupported_request",
    "generation_failed",
    "validation_failed",
]
ValidationStatus = Literal["valid", "invalid", "not_run"]
DraftStatus = Literal["success", "needs_clarification", "unsupported_request"]


class SQLGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=2000)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Question must not be blank.")
        return normalized


class SQLValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: UUID
    sql_query: str = Field(min_length=1, max_length=10000)

    @field_validator("sql_query")
    @classmethod
    def normalize_sql(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("SQL query must not be blank.")
        return normalized


class SQLValidationResponse(BaseModel):
    is_valid: bool
    database_dialect: Literal["sqlite", "postgresql"]
    query_type: str | None
    validation_errors: list[str]
    tables_used: list[str]


class SQLExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql_query: str = Field(min_length=1, max_length=10000)
    page_size: int | None = Field(default=None, ge=1)
    offset: int = Field(default=0, ge=0)
    conversation_id: UUID | None = None

    @field_validator("sql_query")
    @classmethod
    def normalize_sql(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("SQL query must not be blank.")
        return normalized


class ExecutionColumn(BaseModel):
    name: str
    data_type: str | None = None


class SQLExecutionResponse(BaseModel):
    execution_id: UUID
    status: ExecutionStatus
    connection_id: UUID | None = None
    created_at: datetime | None = None
    columns: list[ExecutionColumn]
    rows: list[list[object | None]]
    row_count: int
    execution_duration_ms: float
    truncated: bool
    error: str | None = None
    validation_errors: list[str] = Field(default_factory=list)


class SQLGenerationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DraftStatus
    generated_sql: str | None = Field(default=None, max_length=10000)
    explanation: str = Field(min_length=1, max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=10)


class SQLGenerationResponse(BaseModel):
    status: GenerationStatus
    generated_sql: str | None = None
    explanation: str
    tables_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    validation_status: ValidationStatus
    validation_errors: list[str] = Field(default_factory=list)
    database_dialect: Literal["sqlite", "postgresql"]
