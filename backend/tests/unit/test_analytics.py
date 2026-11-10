import csv
import io
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from app.analytics.engine import analyze_execution
from app.analytics.recommendations import recommend_charts
from app.analytics.schemas import NumericStatistics
from app.analytics.service import (
    answer_analytics_follow_up,
    export_result_csv,
)
from app.db.models import DatabaseConnection, QueryHistory
from app.database_targets.connection_manager import connection_manager
from app.sql.schemas import ExecutionColumn, SQLExecutionResponse


def _result(
    columns: list[tuple[str, str | None]],
    rows: list[list[object | None]],
    *,
    truncated: bool = False,
) -> SQLExecutionResponse:
    return SQLExecutionResponse(
        execution_id=uuid4(),
        status="success",
        columns=[
            ExecutionColumn(name=name, data_type=data_type)
            for name, data_type in columns
        ],
        rows=rows,
        row_count=len(rows),
        execution_duration_ms=1,
        truncated=truncated,
    )


def test_analytics_calculates_statistics_nulls_categories_and_groups() -> None:
    result = _result(
        [("category", "TEXT"), ("amount", "REAL")],
        [
            ["books", 10],
            ["books", 20],
            ["games", 5],
            ["games", None],
            [None, 5],
        ],
    )

    summary = analyze_execution(result)

    amount = next(column for column in summary.columns if column.name == "amount")
    category = next(column for column in summary.columns if column.name == "category")
    assert amount.numeric_statistics == NumericStatistics(
        minimum=5,
        maximum=20,
        mean=10,
        median=7.5,
        total=40,
    )
    assert amount.null_count == 1
    assert category.null_count == 1
    assert category.distinct_count == 2
    assert [(item.value, item.count) for item in category.category_frequencies] == [
        ("books", 2),
        ("games", 2),
    ]
    assert {
        (item.category, item.value_column, item.total)
        for item in category.grouped_summaries
    } == {("books", "amount", 30), ("games", "amount", 5)}


def test_analytics_handles_empty_mixed_and_truncated_results() -> None:
    empty = analyze_execution(_result([("amount", "INTEGER")], []))
    assert empty.row_count == 0
    assert empty.columns[0].numeric_statistics is None
    assert "no rows" in empty.observations[0].casefold()

    mixed = analyze_execution(
        _result(
            [("amount", None), ("label", "TEXT"), ("id", None)],
            [[1, "alpha", "001"], ["bad", "beta", "002"], [None, "beta", "003"]],
            truncated=True,
        )
    )
    assert mixed.columns[0].numeric_statistics is None
    assert mixed.columns[1].category_frequencies[0].value == "beta"
    assert mixed.columns[2].numeric_statistics is None
    assert mixed.truncated is True
    assert any("bounded rows" in observation for observation in mixed.observations)


def test_analytics_processes_bounded_large_result_without_expanding_rows() -> None:
    rows = [[index % 5, float(index)] for index in range(500)]
    summary = analyze_execution(
        _result([("category", "INTEGER"), ("amount", "REAL")], rows, truncated=True)
    )
    assert summary.row_count == 500
    assert summary.columns[1].numeric_statistics is not None
    assert summary.columns[1].numeric_statistics.total == 124750
    assert summary.truncated is True


def test_date_ranges_and_numeric_trends_are_grouped_by_date() -> None:
    result = _result(
        [("created_at", None), ("revenue", "DECIMAL"), ("units", "INTEGER")],
        [
            ["2025-01-01", "10.5", 1],
            ["2025-01-01", "5.5", 2],
            ["2025-01-02", "8.0", 4],
        ],
    )

    summary = analyze_execution(result)

    date_column = summary.columns[0]
    assert date_column.date_minimum.startswith("2025-01-01")
    assert date_column.date_maximum.startswith("2025-01-02")
    assert {
        (point.value_column, point.date, point.total, point.count)
        for point in date_column.trend
    } == {
        ("revenue", "2025-01-01", 16, 2),
        ("revenue", "2025-01-02", 8, 1),
        ("units", "2025-01-01", 3, 2),
        ("units", "2025-01-02", 4, 1),
    }


def test_date_column_without_numeric_values_has_no_trend() -> None:
    summary = analyze_execution(
        _result([("created_at", "DATE")], [["2025-01-01"], ["2025-01-02"]])
    )

    assert summary.columns[0].date_minimum.startswith("2025-01-01")
    assert summary.columns[0].trend == []
    assert summary.columns[0].date_granularity is None


def test_extreme_numeric_values_are_skipped_safely() -> None:
    summary = analyze_execution(
        _result(
            [("amount", "DECIMAL")],
            [["1e999999"], ["2"]],
        )
    )

    assert summary.columns[0].numeric_statistics is None


def test_chart_recommendations_have_valid_chart_ready_fields() -> None:
    result = _result(
        [
            ("category", "TEXT"),
            ("amount", "REAL"),
            ("created_at", "DATE"),
            ("units", "INTEGER"),
        ],
        [
            ["books", 10, "2025-01-01", 2],
            ["games", 20, "2025-01-02", 4],
            ["books", 15, "2025-01-03", 3],
        ],
    )
    summary = analyze_execution(result)

    charts = recommend_charts(result, summary)

    types = {chart.chart_type for chart in charts.recommendations}
    assert {"bar", "pie", "line", "area", "scatter"} <= types
    for chart in charts.recommendations:
        assert chart.suitable is True
        assert chart.data
        assert set(chart.required_data_fields) <= set(chart.data[0])


def test_unsuitable_empty_data_has_explicit_reason() -> None:
    result = _result([("label", "TEXT")], [])
    charts = recommend_charts(result, analyze_execution(result))
    assert charts.suitable is False
    assert charts.recommendations == []
    assert "no rows" in (charts.reason or "")


def test_chart_recommends_bounded_categories_when_each_value_is_unique() -> None:
    result = _result(
        [("category", "TEXT"), ("amount", "REAL")],
        [["books", 12.5], ["games", 7], ["music", 20]],
    )

    charts = recommend_charts(result, analyze_execution(result))

    assert any(
        chart.chart_type == "bar" and chart.x_axis_column == "category"
        for chart in charts.recommendations
    )


def test_follow_up_questions_use_local_cached_statistics_without_groq() -> None:
    result = _result(
        [("category", "TEXT"), ("amount", "REAL"), ("created_at", "DATE")],
        [
            ["books", 10, "2025-01-01"],
            ["books", 20, "2025-01-02"],
            ["games", 15, "2025-02-01"],
        ],
    )

    average = answer_analytics_follow_up(result, "What is the average amount?")
    best = answer_analytics_follow_up(result, "Which category has the highest amount?")
    month = answer_analytics_follow_up(result, "Which month performed best?")
    distribution = answer_analytics_follow_up(result, "Show distribution by category")

    assert "15" in average.answer
    assert "books" in best.answer
    assert "2025-01" in month.answer
    assert "books" in distribution.answer
    assert all(item.source == "cached_result" for item in (average, best, month, distribution))


def test_csv_formula_injection_is_neutralized_but_numeric_negative_is_preserved() -> None:
    result = _result(
        [("=header", None), ("formula", "TEXT"), ("negative_text", "TEXT"), ("amount", "REAL")],
        [["=1+1", "+cmd", " -1+1", -2]],
    )

    output = export_result_csv(result)
    rows = list(csv.reader(io.StringIO(output)))

    assert rows[0][0] == "'=header"
    assert rows[1] == ["'=1+1", "'+cmd", "' -1+1", "-2"]


def _create_analytics_database(path: Path) -> None:
    with sqlite3.connect(path) as database:
        database.executescript(
            """
            CREATE TABLE sales (
                id INTEGER PRIMARY KEY,
                category TEXT,
                amount REAL,
                created_at TEXT
            );
            INSERT INTO sales (category, amount, created_at) VALUES
                ('books', 10, '2025-01-01'),
                ('books', 20, '2025-01-02'),
                ('games', 15, '2025-02-01'),
                ('games', NULL, '2025-02-02');
            """
        )


@pytest.fixture
def uploaded_analytics_connection(
    authenticated_client,
    connection_settings,
    tmp_path: Path,
) -> str:
    path = tmp_path / "analytics-target.sqlite3"
    _create_analytics_database(path)
    with path.open("rb") as source:
        response = authenticated_client["client"](
            "POST",
            "/api/v1/connections/sqlite/upload",
            headers=authenticated_client["headers"],
            data={"name": "Analytics target"},
            files={"file": (path.name, source, "application/octet-stream")},
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _execute_sales(authenticated_client, connection_id: str) -> dict[str, object]:
    response = authenticated_client["client"](
        "POST",
        f"/api/v1/connections/{connection_id}/execute",
        headers=authenticated_client["headers"],
        json={
            "sql_query": (
                "SELECT category, amount, created_at FROM sales ORDER BY id"
            )
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.usefixtures("connection_settings")
def test_analytics_apis_reuse_cached_real_sqlite_results_without_reexecution(
    authenticated_client,
    uploaded_analytics_connection: str,
) -> None:
    execution = _execute_sales(authenticated_client, uploaded_analytics_connection)
    engine = connection_manager._engines[UUID(uploaded_analytics_connection)]
    statements: list[str] = []

    def capture_statement(
        connection,
        cursor,
        statement,
        parameters,
        context,
        executemany,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        analytics = authenticated_client["client"](
            "GET",
            f"/api/v1/executions/{execution['execution_id']}/analytics",
            headers=authenticated_client["headers"],
        )
        charts = authenticated_client["client"](
            "GET",
            f"/api/v1/executions/{execution['execution_id']}/charts",
            headers=authenticated_client["headers"],
        )
        csv_response = authenticated_client["client"](
            "GET",
            f"/api/v1/executions/{execution['execution_id']}/export/csv",
            headers=authenticated_client["headers"],
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert analytics.status_code == charts.status_code == csv_response.status_code == 200
    assert analytics.json()["row_count"] == 4
    assert analytics.json()["columns"][1]["numeric_statistics"]["mean"] == "15.0"
    assert charts.json()["suitable"] is True
    assert any(chart["chart_type"] == "bar" for chart in charts.json()["recommendations"])
    assert "text/csv" in csv_response.headers["content-type"]
    assert execution["execution_id"] in csv_response.headers["content-disposition"]
    assert len(statements) == 0


def test_analytics_endpoints_require_authentication(api_client) -> None:
    for suffix in ("analytics", "charts", "export/csv"):
        response = api_client(
            "GET",
            f"/api/v1/executions/{uuid4()}/{suffix}",
        )
        assert response.status_code == 401
    response = api_client(
        "POST",
        f"/api/v1/executions/{uuid4()}/analytics/follow-up",
        json={"question": "What is the average?"},
    )
    assert response.status_code == 401


@pytest.mark.usefixtures("connection_settings")
def test_analytics_enforces_execution_ownership_and_expiration(
    authenticated_client,
    api_client,
    test_session_factory,
    uploaded_analytics_connection: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.sql import execution_service

    execution = _execute_sales(authenticated_client, uploaded_analytics_connection)
    registration = api_client(
        "POST",
        "/api/v1/auth/register",
        json={
            "username": "analytics-other",
            "email": "analytics-other@example.com",
            "password": "Another-strong-password-123",
        },
    )
    login = api_client(
        "POST",
        "/api/v1/auth/login",
        json={
            "email": "analytics-other@example.com",
            "password": "Another-strong-password-123",
        },
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    hidden = api_client(
        "GET",
        f"/api/v1/executions/{execution['execution_id']}/analytics",
        headers=other_headers,
    )
    assert registration.status_code == 201
    assert hidden.status_code == 404

    foreign_connection_id = uuid4()
    foreign_execution_id = uuid4()
    with test_session_factory() as session:
        session.add(
            DatabaseConnection(
                id=foreign_connection_id,
                user_id=UUID(registration.json()["id"]),
                name="Other user's connection",
                database_type="sqlite",
                connection_metadata={},
            )
        )
        session.add(
            QueryHistory(
                id=foreign_execution_id,
                user_id=authenticated_client["user_id"],
                connection_id=foreign_connection_id,
                natural_language_question="A mismatched ownership record",
                generated_sql="SELECT 1",
                execution_status="succeeded",
            )
        )
        session.commit()

    mismatched_connection = authenticated_client["client"](
        "GET",
        f"/api/v1/executions/{foreign_execution_id}/analytics",
        headers=authenticated_client["headers"],
    )
    assert mismatched_connection.status_code == 404

    monkeypatch.setattr(
        execution_service.execution_result_cache,
        "get",
        lambda user_id, execution_id: None,
    )
    expired = authenticated_client["client"](
        "GET",
        f"/api/v1/executions/{execution['execution_id']}/analytics",
        headers=authenticated_client["headers"],
    )
    assert expired.status_code == 410


@pytest.mark.usefixtures("connection_settings")
def test_follow_up_endpoint_answers_from_cached_result(
    authenticated_client,
    uploaded_analytics_connection: str,
) -> None:
    execution = _execute_sales(authenticated_client, uploaded_analytics_connection)

    response = authenticated_client["client"](
        "POST",
        f"/api/v1/executions/{execution['execution_id']}/analytics/follow-up",
        headers=authenticated_client["headers"],
        json={"question": "Which category has the highest amount?"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["source"] == "cached_result"
    assert "books" in response.json()["answer"]
