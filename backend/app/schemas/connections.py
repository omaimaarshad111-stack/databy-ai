from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class PostgreSQLConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=63)
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)
    sslmode: Literal[
        "disable",
        "allow",
        "prefer",
        "require",
        "verify-ca",
        "verify-full",
    ] = "require"

    @field_validator("name", "host", "database_name", "username")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field must not be blank.")
        return normalized

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        if not value or any(character in value for character in "/\\@?#") or any(
            character.isspace() for character in value
        ):
            raise ValueError("Host must be a hostname or IP address, not a URL.")
        return value


class SQLiteUploadResponse(BaseModel):
    id: UUID
    name: str
    database_type: Literal["sqlite"]
    connection_status: Literal["connected"]
    last_tested_at: datetime
    created_at: datetime


class ConnectionResponse(BaseModel):
    id: UUID
    name: str
    database_type: Literal["sqlite", "postgresql"]
    connection_status: Literal["connected", "failed"] | None
    last_tested_at: datetime | None
    metadata: dict[str, str | int]
    created_at: datetime
    updated_at: datetime


class ConnectionTestResponse(BaseModel):
    success: bool
    message: str
    last_tested_at: datetime


class ColumnSchema(BaseModel):
    name: str
    data_type: str
    nullable: bool
    default: str | None = None


class ForeignKeySchema(BaseModel):
    name: str | None = None
    columns: list[str]
    referred_schema: str | None = None
    referred_table: str
    referred_columns: list[str]


class IndexSchema(BaseModel):
    name: str
    columns: list[str]
    unique: bool


class TableSchema(BaseModel):
    name: str
    columns: list[ColumnSchema]
    primary_key: list[str]
    foreign_keys: list[ForeignKeySchema]
    unique_constraints: list[list[str]]
    indexes: list[IndexSchema]


class SchemaInfo(BaseModel):
    name: str
    tables: list[TableSchema]


class DatabaseSchemaResponse(BaseModel):
    connection_id: UUID
    database_type: Literal["sqlite", "postgresql"]
    schemas: list[SchemaInfo]
