import logging
from typing import cast

from app.agent.intent import answer_general_question, classify_intent
from app.agent.result_analysis import summarize_execution
from app.agent.state import AssistantState
from app.database_targets.exceptions import TargetConnectionError
from app.services.connection_service import (
    get_owned_connection,
    inspect_connection_schema,
)
from app.sql.dialects import DatabaseDialect
from app.sql.exceptions import SQLGenerationError
from app.sql.execution_service import execute_query
from app.sql.schemas import SQLExecutionRequest
from app.sql.validator import validate_read_only_sql

logger = logging.getLogger(__name__)


def _step(
    state: AssistantState,
    name: str,
    status: str,
    message: str,
) -> list[dict[str, str]]:
    return [
        *state.get("steps", []),
        {"name": name, "status": status, "message": message},
    ]


def classify_request(state: AssistantState) -> dict[str, object]:
    result = classify_intent(
        state["question"],
        state["conversation_context"],
    )
    return {
        "intent": result.intent,
        "intent_message": result.user_facing_message,
        "steps": _step(state, "understanding", "completed", "Request classified."),
    }


def retrieve_schema(state: AssistantState) -> dict[str, object]:
    try:
        connection = get_owned_connection(
            state["db"], state["user"], state["connection_id"]
        )
        schemas = inspect_connection_schema(connection)
    except TargetConnectionError:
        return {
            "workflow_status": "failed",
            "workflow_error": "The connected database schema could not be retrieved.",
            "steps": _step(state, "schema", "failed", "Schema retrieval failed."),
        }

    return {
        "schemas": schemas,
        "database_dialect": connection.database_type,
        "steps": _step(
            state,
            "schema",
            "completed",
            "Retrieved schema for the selected connection.",
        ),
    }


def _contextual_question(state: AssistantState) -> str:
    history = state["conversation_context"][-8:]
    if not history:
        return state["question"]
    from app.core.config import get_settings

    remaining = max(0, get_settings().sql_generation_max_question_chars - len(state["question"]) - 160)
    context = "\n".join(
        f"{message['role']}: {message['content'][:1000]}" for message in history
    )
    context = context[-remaining:] if remaining else ""
    if not context:
        return state["question"]
    return (
        "Use this recent conversation only to resolve references in the latest "
        "request. The latest request is authoritative.\n"
        f"Recent conversation:\n{context}\n\n"
        f"Latest request:\n{state['question']}"
    )


def generate_query(state: AssistantState) -> dict[str, object]:
    from app.sql.generator import generate_sql

    try:
        result = generate_sql(
            _contextual_question(state),
            cast(DatabaseDialect, state["database_dialect"]),
            state["schemas"],
        )
    except SQLGenerationError as exc:
        logger.warning("Assistant SQL generation failed (%s).", type(exc).__name__)
        return {
            "workflow_status": "failed",
            "workflow_error": "SQL generation is temporarily unavailable.",
            "steps": _step(state, "sql_generation", "failed", "SQL generation failed."),
        }

    return {
        "generation": result,
        "sql_query": result.generated_sql,
        "validation_errors": result.validation_errors,
        "steps": _step(
            state,
            "sql_generation",
            "completed" if result.status == "success" else "failed",
            "Generated a read-only SQL statement."
            if result.status == "success"
            else result.explanation,
        ),
    }


def validate_query(state: AssistantState) -> dict[str, object]:
    result = validate_read_only_sql(
        state["sql_query"],
        cast(DatabaseDialect, state["database_dialect"]),
        state["schemas"],
    )
    return {
        "validation_errors": result.validation_errors,
        "steps": _step(
            state,
            "sql_validation",
            "completed" if result.is_valid else "failed",
            "SQL passed server-side validation."
            if result.is_valid
            else "SQL was rejected by server-side validation.",
        ),
    }


def execute_query_node(state: AssistantState) -> dict[str, object]:
    response = execute_query(
        state["db"],
        state["user"],
        state["connection_id"],
        SQLExecutionRequest(
            sql_query=state["sql_query"],
            conversation_id=state["conversation_id"],
        ),
        natural_language_question=state["question"],
    )
    status = "completed" if response.status == "success" else "failed"
    return {
        "execution": response,
        "steps": _step(
            state,
            "execution",
            status,
            "Query executed against the selected database."
            if status == "completed"
            else "Query execution did not succeed.",
        ),
    }


def analyze_results(state: AssistantState) -> dict[str, object]:
    return {
        "analysis": summarize_execution(state["execution"]),
        "steps": _step(
            state,
            "result_analysis",
            "completed",
            "Analyzed the returned result metadata and bounded rows locally.",
        ),
    }


def _schema_answer(state: AssistantState) -> str:
    schemas = state.get("schemas", [])
    tables = [
        f"{schema.name}.{table.name} ({', '.join(column.name for column in table.columns)})"
        for schema in schemas
        for table in schema.tables
    ]
    if not tables:
        return "The selected database has no tables available to explore."
    listing = "; ".join(tables[:30])
    suffix = " Additional tables were omitted from this summary." if len(tables) > 30 else ""
    return f"Available tables and columns: {listing}.{suffix}"


def respond(state: AssistantState) -> dict[str, object]:
    intent = state.get("intent")
    status = state.get("workflow_status")
    execution = state.get("execution")
    generation = state.get("generation")

    if status == "failed":
        answer = state.get("workflow_error", "The request could not be completed.")
    elif intent == "schema_question":
        answer = _schema_answer(state)
    elif intent == "unsupported_request":
        answer = state.get(
            "intent_message",
            "This assistant supports read-only database questions only.",
        )
    elif intent == "clarification_needed":
        answer = state.get(
            "intent_message",
            "Please clarify which data or time period you want to query.",
        )
    elif intent == "general_question":
        answer = answer_general_question(
            state["question"],
            state["conversation_context"],
        )
    elif generation is not None and generation.status != "success":
        answer = (
            "The generated SQL did not pass server-side validation and was not executed."
            if generation.status == "validation_failed"
            else generation.explanation
        )
    elif state.get("validation_errors"):
        answer = "The generated SQL did not pass server-side validation and was not executed."
    elif execution is not None and execution.status != "success":
        answer = execution.error or "The query could not be executed."
    elif execution is not None:
        answer = state.get("analysis", "The query completed successfully.")
        if generation is not None and generation.explanation:
            answer = f"{generation.explanation} {answer}"
    else:
        answer = "The request could not be completed."

    return {
        "answer": answer,
        "workflow_status": status or (
            "completed" if execution is None or execution.status == "success" else "failed"
        ),
        "steps": _step(state, "response", "completed", "Prepared the user-facing response."),
    }
