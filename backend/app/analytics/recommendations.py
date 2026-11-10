from decimal import Decimal
import math

from app.analytics.schemas import (
    AnalyticsSummary,
    ChartRecommendation,
    ChartRecommendationsResponse,
    GroupSummary,
)
from app.sql.schemas import SQLExecutionResponse

_MAX_RECOMMENDATIONS = 10
_MAX_SCATTER_POINTS = 500
_MAX_DISTRIBUTION_CATEGORIES = 12


def _column_values(
    result: SQLExecutionResponse,
    column_name: str,
) -> list[object | None]:
    try:
        index = next(
            index
            for index, column in enumerate(result.columns)
            if column.name == column_name
        )
    except StopIteration:
        return []
    return [row[index] if index < len(row) else None for row in result.rows]


def _grouped_data(
    groups: list[GroupSummary],
    category_name: str,
    numeric_name: str,
) -> list[dict[str, object | None]]:
    data: list[dict[str, object | None]] = []
    for group in groups:
        value = _number(group.total)
        if group.category is not None and value is not None:
            data.append({category_name: group.category, numeric_name: value})
    return data


def _number(value: object | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(Decimal(str(value)))
    except (ValueError, ArithmeticError):
        return None
    return number if math.isfinite(number) else None


def recommend_charts(
    result: SQLExecutionResponse,
    summary: AnalyticsSummary,
) -> ChartRecommendationsResponse:
    if not result.rows:
        return ChartRecommendationsResponse(
            execution_id=result.execution_id,
            suitable=False,
            reason="The result contains no rows to visualize.",
            recommendations=[],
        )

    recommendations: list[ChartRecommendation] = []
    categorical = [
        column
        for column in summary.columns
        if column.category_frequencies
        and len(column.category_frequencies) >= 2
        and column.grouped_summaries
    ]
    numeric = [
        column for column in summary.columns if column.numeric_statistics is not None
    ]
    date_columns = [column for column in summary.columns if column.trend]

    for category in categorical:
        for numeric_column in numeric:
            groups = [
                group
                for group in category.grouped_summaries
                if group.value_column == numeric_column.name
                and group.category is not None
            ]
            if not groups:
                continue
            chart_data = _grouped_data(groups, category.name, numeric_column.name)
            if len(chart_data) < 2:
                continue
            recommendations.append(
                ChartRecommendation(
                    chart_type="bar",
                    title=f"{numeric_column.name} by {category.name}",
                    x_axis_column=category.name,
                    y_axis_column=numeric_column.name,
                    explanation="Compares the grouped total across returned categories.",
                    required_data_fields=[category.name, numeric_column.name],
                    suitable=True,
                    suitability_reason="Multiple categories and numeric values are available.",
                    data=chart_data,
                )
            )
            if len(recommendations) >= _MAX_RECOMMENDATIONS:
                break
            numeric_values = [
                Decimal(str(point[numeric_column.name]))
                for point in chart_data
                if point[numeric_column.name] is not None
            ]
            if (
                2 <= len(chart_data) <= _MAX_DISTRIBUTION_CATEGORIES
                and numeric_values
                and all(value >= 0 for value in numeric_values)
                and sum(numeric_values) > 0
            ):
                recommendations.append(
                    ChartRecommendation(
                        chart_type="pie",
                        title=f"{numeric_column.name} distribution by {category.name}",
                        x_axis_column=category.name,
                        y_axis_column=numeric_column.name,
                        explanation="Shows each category's share of the returned grouped total.",
                        required_data_fields=[category.name, numeric_column.name],
                        suitable=True,
                        suitability_reason="The grouped values are non-negative and form a small distribution.",
                        data=chart_data,
                    )
                )
            if len(recommendations) >= _MAX_RECOMMENDATIONS:
                break
        if len(recommendations) >= _MAX_RECOMMENDATIONS:
            break

    for date_column in date_columns:
        value_columns = list(dict.fromkeys(point.value_column for point in date_column.trend))
        for numeric_name in value_columns:
            trend_data: list[dict[str, object | None]] = []
            for point in date_column.trend:
                if point.value_column != numeric_name:
                    continue
                value = _number(point.total)
                if value is not None:
                    trend_data.append({date_column.name: point.date, numeric_name: value})
            if len(trend_data) < 2:
                continue
            for chart_type in ("line", "area"):
                recommendations.append(
                    ChartRecommendation(
                        chart_type=chart_type,
                        title=f"{numeric_name} over {date_column.name}",
                        x_axis_column=date_column.name,
                        y_axis_column=numeric_name,
                        explanation=(
                            "Shows totals grouped by date from the returned rows."
                            if chart_type == "line"
                            else "Emphasizes the magnitude of totals across date buckets."
                        ),
                        required_data_fields=[date_column.name, numeric_name],
                        suitable=True,
                        suitability_reason="At least two date buckets have numeric values.",
                        data=trend_data,
                    )
                )
                if len(recommendations) >= _MAX_RECOMMENDATIONS:
                    break
            if len(recommendations) >= _MAX_RECOMMENDATIONS:
                break
        if len(recommendations) >= _MAX_RECOMMENDATIONS:
            break

    for left_index, left in enumerate(numeric):
        if len(recommendations) >= _MAX_RECOMMENDATIONS:
            break
        left_values = _column_values(result, left.name)
        for right in numeric[left_index + 1 :]:
            right_values = _column_values(result, right.name)
            points = []
            for left_value, right_value in zip(
                left_values[:_MAX_SCATTER_POINTS],
                right_values[:_MAX_SCATTER_POINTS],
            ):
                x_value = _number(left_value)
                y_value = _number(right_value)
                if x_value is not None and y_value is not None:
                    points.append({left.name: x_value, right.name: y_value})
            if len(points) < 2:
                continue
            recommendations.append(
                ChartRecommendation(
                    chart_type="scatter",
                    title=f"{left.name} vs {right.name}",
                    x_axis_column=left.name,
                    y_axis_column=right.name,
                    explanation="Displays paired numeric values from the returned rows.",
                    required_data_fields=[left.name, right.name],
                    suitable=True,
                    suitability_reason="At least two rows contain paired numeric values.",
                    data=points,
                )
            )
            if len(recommendations) >= _MAX_RECOMMENDATIONS:
                break
        if len(recommendations) >= _MAX_RECOMMENDATIONS:
            break

    recommendations = recommendations[:_MAX_RECOMMENDATIONS]
    return ChartRecommendationsResponse(
        execution_id=result.execution_id,
        suitable=bool(recommendations),
        reason=None
        if recommendations
        else "The returned columns do not provide a suitable category, date, or numeric pairing.",

        recommendations=recommendations,
    )
