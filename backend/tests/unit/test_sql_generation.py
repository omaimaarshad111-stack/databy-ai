from collections.abc import Sequence

import httpx
import pytest
from groq import APIConnectionError, APITimeoutError

from app.core.config import get_settings
from app.schemas.connections import (
    ColumnSchema,
    ForeignKeySchema,
    SchemaInfo,
    TableSchema,
)
from app.sql.exceptions import GroqProviderError
from app.sql.generator import generate_sql
from app.sql.prompts import build_relevant_schema_context
from app.sql.exceptions import SchemaContextTooLargeError


class FakeModel:
    def __init__(self, responses: Sequence[object]) -> None:
        self.responses = list(responses)
        self.calls: list[object] = []

    def invoke(self, prompt: object) -> object:
        self.calls.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


@pytest.fixture
def schema() -> list[SchemaInfo]:
    return [
        SchemaInfo(
            name="main",
            tables=[
                TableSchema(
                    name="customers",
                    columns=[
                        ColumnSchema(name="id", data_type="INTEGER", nullable=False),
                        ColumnSchema(name="name", data_type="TEXT", nullable=False),
                    ],
                    primary_key=["id"],
                    foreign_keys=[],
                    unique_constraints=[],
                    indexes=[],
                )
            ],
        )
    ]


@pytest.mark.parametrize(
    ("dialect", "query"),
    [
        ("sqlite", "SELECT name FROM customers ORDER BY id LIMIT 5"),
        ("postgresql", "SELECT name FROM customers ORDER BY id LIMIT 5"),
    ],
)
def test_sql_generation_is_schema_validated_for_each_dialect(
    dialect: str,
    query: str,
    schema: list[SchemaInfo],
) -> None:
    model = FakeModel(
        [
            {
                "status": "success",
                "generated_sql": query,
                "explanation": "Lists customer names.",
                "assumptions": [],
            }
        ]
    )

    result = generate_sql(
        "List customer names",
        dialect,  # type: ignore[arg-type]
        schema,
        model=model,
    )

    assert result.status == "success"
    assert result.generated_sql == query
    assert result.validation_status == "valid"
    assert result.tables_used == (
        ["customers"] if dialect == "sqlite" else ["main.customers"]
    )
    assert len(model.calls) == 1
    assert "customers" in str(model.calls[0])


@pytest.mark.parametrize("status", ["needs_clarification", "unsupported_request"])
def test_non_success_generation_does_not_return_sql(
    status: str,
    schema: list[SchemaInfo],
) -> None:
    model = FakeModel(
        [
            {
                "status": status,
                "generated_sql": None,
                "explanation": "The request is ambiguous.",
                "assumptions": [],
            }
        ]
    )

    result = generate_sql("Show spending", "sqlite", schema, model=model)

    assert result.status == status
    assert result.generated_sql is None
    assert result.validation_status == "not_run"


def test_unknown_schema_identifier_is_not_returned_as_valid_sql(
    schema: list[SchemaInfo],
) -> None:
    model = FakeModel(
        [
            {
                "status": "success",
                "generated_sql": "SELECT email FROM customers",
                "explanation": "Lists emails.",
                "assumptions": [],
            }
        ]
    )

    result = generate_sql("List customer emails", "sqlite", schema, model=model)

    assert result.status == "validation_failed"
    assert result.validation_status == "invalid"
    assert any("email" in error for error in result.validation_errors)


def test_malformed_model_responses_retry_only_to_configured_bound(
    schema: list[SchemaInfo],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "sql_generation_max_attempts", 2)
    model = FakeModel([{"unexpected": "shape"}] * 2)

    result = generate_sql("List customers", "sqlite", schema, model=model)

    assert result.status == "generation_failed"
    assert len(model.calls) == 2


def test_provider_failure_is_reported_without_revealing_request_or_key(
    schema: list[SchemaInfo],
) -> None:
    model = FakeModel([APIConnectionError(request=httpx.Request("POST", "https://api.groq.com"))])

    with pytest.raises(GroqProviderError):
        generate_sql("sensitive question", "sqlite", schema, model=model)


def test_provider_timeout_is_reported_without_provider_details(
    schema: list[SchemaInfo],
) -> None:
    model = FakeModel(
        [APITimeoutError(request=httpx.Request("POST", "https://api.groq.com"))]
    )

    with pytest.raises(GroqProviderError) as error:
        generate_sql("List customers", "sqlite", schema, model=model)

    assert str(error.value) == ""


def test_empty_schema_does_not_call_model() -> None:
    model = FakeModel([])

    result = generate_sql("List customers", "sqlite", [], model=model)

    assert result.status == "unsupported_request"
    assert model.calls == []


def test_large_schema_context_keeps_relevant_tables_and_relationships(
    schema: list[SchemaInfo],
) -> None:
    orders = TableSchema(
        name="orders",
        columns=[
            ColumnSchema(name="customer_id", data_type="INTEGER", nullable=False),
            ColumnSchema(name="total", data_type="REAL", nullable=False),
        ],
        primary_key=[],
        foreign_keys=[
            ForeignKeySchema(
                columns=["customer_id"],
                referred_table="customers",
                referred_columns=["id"],
            )
        ],
        unique_constraints=[],
        indexes=[],
    )
    unrelated = TableSchema(
        name="unrelated",
        columns=[
            ColumnSchema(name="payload_" + "x" * 3000, data_type="TEXT", nullable=True)
        ],
        primary_key=[],
        foreign_keys=[],
        unique_constraints=[],
        indexes=[],
    )
    schema[0].tables.extend([orders, unrelated])

    context = build_relevant_schema_context(
        "Show customer spending",
        schema,
        max_chars=2000,
    )

    assert "customers" in context
    assert "orders" in context
    assert "unrelated" not in context
    assert len(context) <= 2000


def test_relevant_schema_is_not_silently_truncated(schema: list[SchemaInfo]) -> None:
    with pytest.raises(SchemaContextTooLargeError):
        build_relevant_schema_context("List customers", schema, max_chars=10)
