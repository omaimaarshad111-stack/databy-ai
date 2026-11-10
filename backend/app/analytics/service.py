import csv
from decimal import Decimal
from io import StringIO
import logging
import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.engine import analyze_execution
from app.analytics.recommendations import recommend_charts
from app.analytics.schemas import (
    AnalyticsFollowUpResponse,
    AnalyticsSummary,
    ChartRecommendationsResponse,
)
from app.db.models import QueryHistory, User
from app.database_targets.exceptions import ConnectionNotFoundError
from app.services.connection_service import get_owned_connection
from app.sql.execution_service import (
    ExecutionNotFoundError,
    get_execution_result,
)
from app.sql.schemas import SQLExecutionResponse

logger = logging.getLogger(__name__)
_FORMULA_PREFIX = re.compile(r"^[\s\x00-\x1f\ufeff]*[=+\-@]")


class ExecutionResultsExpiredError(Exception):
    pass


class ExecutionResultsUnavailableError(Exception):
    pass


class UnsupportedAnalyticsFollowUpError(Exception):
    pass


def get_owned_execution_result(
    db: Session,
    user: User,
    execution_id: UUID,
) -> SQLExecutionResponse:
    history = db.scalar(
        select(QueryHistory).where(
            QueryHistory.id == execution_id,
            QueryHistory.user_id == user.id,
        )
    )
    if history is None:
        raise ExecutionNotFoundError
    try:
        get_owned_connection(db, user, history.connection_id)
    except ConnectionNotFoundError:
        raise ExecutionNotFoundError from None

    result = get_execution_result(db, user, execution_id)
    if result.status == "results_expired":
        raise ExecutionResultsExpiredError
    if result.status != "success":
        raise ExecutionResultsUnavailableError
    return result


def get_analytics_summary(result: SQLExecutionResponse) -> AnalyticsSummary:
    return analyze_execution(result)


def get_chart_recommendations(
    result: SQLExecutionResponse,
) -> ChartRecommendationsResponse:
    summary = analyze_execution(result)
    return recommend_charts(result, summary)


def _csv_value(value: object | None) -> str | int | float:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    if _FORMULA_PREFIX.match(text):
        return f"'{text}"
    return text


def export_result_csv(result: SQLExecutionResponse) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([_csv_value(column.name) for column in result.columns])
    for row in result.rows:
        writer.writerow([_csv_value(value) for value in row])
    return output.getvalue()


def _select_column(candidates: list[str], question: str) -> str | None:
    lowered = question.casefold()
    mentioned = [name for name in candidates if name.casefold() in lowered]
    if len(mentioned) == 1:
        return mentioned[0]
    return candidates[0] if len(candidates) == 1 else None


def answer_analytics_follow_up(
    result: SQLExecutionResponse,
    question: str,
) -> AnalyticsFollowUpResponse:
    summary = analyze_execution(result)
    lowered = question.casefold()

    date_columns = [column for column in summary.columns if column.trend]
    if any(token in lowered for token in ("month", "monthly")) and date_columns:
        date_column = date_columns[0]
        trend_metrics = list(
            dict.fromkeys(point.value_column for point in date_column.trend)
        )
        metric = _select_column(trend_metrics, lowered)
        if metric is None:
            raise UnsupportedAnalyticsFollowUpError(
                "Please name the numeric measure to compare by month, or continue in the assistant for a new query."
            )
        monthly_totals: dict[str, Decimal] = {}
        for point in date_column.trend:
            if point.value_column != metric:
                continue
            month = point.date[:7]
            monthly_totals[month] = monthly_totals.get(month, Decimal(0)) + point.total
        if monthly_totals:
            best_month = max(monthly_totals, key=monthly_totals.get)
            answer = f"{best_month} has the highest returned total ({monthly_totals[best_month]})."
            return AnalyticsFollowUpResponse(
                execution_id=result.execution_id,
                answer=answer,
                source="cached_result",
            )

    if any(token in lowered for token in ("distribution", "breakdown", "frequency")):
        category_columns = [
            column for column in summary.columns if column.category_frequencies
        ]
        name = _select_column([column.name for column in category_columns], lowered)
        if name is None:
            raise UnsupportedAnalyticsFollowUpError(
                "The cached results do not identify one category column. Continue in the assistant with a more specific question."
            )
        selected = next(column for column in category_columns if column.name == name)
        values = ", ".join(
            f"{item.value!s}: {item.count}"
            for item in selected.category_frequencies
        )
        return AnalyticsFollowUpResponse(
            execution_id=result.execution_id,
            answer=f"Returned-row distribution for {name}: {values}.",
            source="cached_result",
        )

    if any(token in lowered for token in ("average", "mean", "avg")):
        numeric_columns = [
            column for column in summary.columns if column.numeric_statistics is not None
        ]
        name = _select_column([column.name for column in numeric_columns], lowered)
        if name is None:
            raise UnsupportedAnalyticsFollowUpError(
                "Please name the numeric column to average, or continue in the assistant for a new query."
            )
        selected = next(column for column in numeric_columns if column.name == name)
        statistics = selected.numeric_statistics
        if statistics is None:
            raise UnsupportedAnalyticsFollowUpError(
                "No numeric values were available in the cached results."
            )
        return AnalyticsFollowUpResponse(
            execution_id=result.execution_id,
            answer=f"The average {name} across returned rows is {statistics.mean}.",
            source="cached_result",
        )

    if any(token in lowered for token in ("highest", "best", "most")):
        group_columns = [
            column for column in summary.columns if column.grouped_summaries
        ]
        name = _select_column([column.name for column in group_columns], lowered)
        if name is None:
            raise UnsupportedAnalyticsFollowUpError(
                "The cached results do not contain one unambiguous grouped summary. Continue in the assistant for a new query."
            )
        selected = next(column for column in group_columns if column.name == name)
        metrics = list(
            dict.fromkeys(
                group.value_column for group in selected.grouped_summaries
            )
        )
        metric = _select_column(metrics, lowered)
        if metric is None:
            raise UnsupportedAnalyticsFollowUpError(
                "Please name the numeric measure to compare, or continue in the assistant for a new query."
            )
        best_group = max(
            [
                group
                for group in selected.grouped_summaries
                if group.value_column == metric
            ],
            key=lambda group: group.total,
        )
        return AnalyticsFollowUpResponse(
            execution_id=result.execution_id,
            answer=(
                f"{best_group.category!s} has the highest {best_group.value_column} "
                f"total ({best_group.total}) in the returned rows."
            ),
            source="cached_result",
        )

    raise UnsupportedAnalyticsFollowUpError(
        "This question cannot be answered deterministically from the current result window. Continue in the assistant to run a new validated query."
    )
