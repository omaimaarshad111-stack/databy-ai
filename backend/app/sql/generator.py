import logging
from typing import Protocol

from groq import APIError
from langchain_core.exceptions import OutputParserException
from langchain_groq import ChatGroq
from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.connections import SchemaInfo
from app.sql.dialects import DatabaseDialect
from app.sql.exceptions import (
    GroqProviderError,
    MissingGroqAPIKeyError,
    SchemaContextTooLargeError,
)
from app.sql.prompts import build_relevant_schema_context, build_system_prompt
from app.sql.schemas import SQLGenerationDraft, SQLGenerationResponse
from app.sql.validator import validate_read_only_sql

logger = logging.getLogger(__name__)


class StructuredSQLModel(Protocol):
    def invoke(self, input: list[tuple[str, str]]) -> object: ...


def get_sql_model() -> StructuredSQLModel:
    settings = get_settings()
    if not settings.groq_api_key:
        raise MissingGroqAPIKeyError("GROQ_API_KEY is not configured.")
    model = ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0,
        timeout=settings.groq_timeout_seconds,
        max_retries=0,
    )
    return model.with_structured_output(SQLGenerationDraft)


def generate_sql(
    question: str,
    database_dialect: DatabaseDialect,
    schemas: list[SchemaInfo],
    *,
    model: StructuredSQLModel | None = None,
) -> SQLGenerationResponse:
    settings = get_settings()
    try:
        schema_context = build_relevant_schema_context(
            question,
            schemas,
            settings.sql_generation_max_schema_chars,
        )
    except SchemaContextTooLargeError as exc:
        return SQLGenerationResponse(
            status="needs_clarification",
            explanation=str(exc),
            validation_status="not_run",
            database_dialect=database_dialect,
        )

    if schema_context == "[]":
        return SQLGenerationResponse(
            status="unsupported_request",
            explanation="This database has no tables available for SQL generation.",
            validation_status="not_run",
            database_dialect=database_dialect,
        )

    if len(question) > settings.sql_generation_max_question_chars:
        return SQLGenerationResponse(
            status="generation_failed",
            explanation="The question exceeds the configured length limit.",
            validation_status="not_run",
            database_dialect=database_dialect,
        )

    sql_model = model or get_sql_model()
    prompt = [
        ("system", build_system_prompt(database_dialect, schema_context)),
        ("human", question),
    ]
    draft: SQLGenerationDraft | None = None
    for attempt in range(settings.sql_generation_max_attempts):
        try:
            response = sql_model.invoke(prompt)
            draft = (
                response
                if isinstance(response, SQLGenerationDraft)
                else SQLGenerationDraft.model_validate(response)
            )
            if draft.status == "success" and not draft.generated_sql:
                raise ValueError("A successful result must contain SQL.")
            if draft.status != "success" and draft.generated_sql is not None:
                raise ValueError("Non-success results must not contain SQL.")
            break
        except (OutputParserException, ValidationError, ValueError, TypeError):
            if attempt + 1 == settings.sql_generation_max_attempts:
                logger.warning("SQL model returned a malformed structured response.")
                return SQLGenerationResponse(
                    status="generation_failed",
                    explanation="The SQL model returned an invalid response. Please retry.",
                    validation_status="not_run",
                    database_dialect=database_dialect,
                )
        except APIError as exc:
            logger.warning("Groq SQL generation request failed (%s).", type(exc).__name__)
            raise GroqProviderError from None

    if draft is None:
        return SQLGenerationResponse(
            status="generation_failed",
            explanation="SQL generation did not return a usable response.",
            validation_status="not_run",
            database_dialect=database_dialect,
        )

    if draft.status != "success" or draft.generated_sql is None:
        return SQLGenerationResponse(
            status=draft.status,
            explanation=draft.explanation,
            assumptions=draft.assumptions,
            validation_status="not_run",
            database_dialect=database_dialect,
        )

    if len(draft.generated_sql) > settings.sql_max_query_chars:
        return SQLGenerationResponse(
            status="generation_failed",
            explanation="The generated SQL exceeds the configured length limit.",
            validation_status="not_run",
            database_dialect=database_dialect,
        )

    validation = validate_read_only_sql(
        draft.generated_sql,
        database_dialect,
        schemas,
    )
    return SQLGenerationResponse(
        status="success" if validation.is_valid else "validation_failed",
        generated_sql=draft.generated_sql,
        explanation=draft.explanation,
        tables_used=validation.tables_used,
        assumptions=draft.assumptions,
        validation_status="valid" if validation.is_valid else "invalid",
        validation_errors=validation.validation_errors,
        database_dialect=database_dialect,
    )
