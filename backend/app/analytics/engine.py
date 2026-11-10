from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from statistics import median
from typing import TypeAlias

from app.analytics.schemas import (
    AnalyticsSummary,
    CategoryFrequency,
    ColumnAnalytics,
    GroupSummary,
    NumericStatistics,
    TrendPoint,
)
from app.sql.schemas import SQLExecutionResponse

Scalar: TypeAlias = str | int | float | bool | None
_IDENTIFIER_NAMES = re.compile(r"(^id$|_id$|(^|_)(zip|postal|phone|account|code)($|_))", re.I)
_NUMERIC_TEXT = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_NUMERIC_TYPE = re.compile(
    r"\b(?:tinyint|smallint|mediumint|int(?:eger)?|bigint|serial|numeric|decimal|real|float\d*|double|money)\b",
    re.I,
)
_MAX_CATEGORY_VALUES = 20
_MAX_GROUPS_PER_PAIR = 20
_MAX_GROUP_PAIRS = 40
_MAX_TREND_PAIRS = 40


def _decimal(value: object, *, declared_numeric: bool) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return None
        if (
            not number.is_finite()
            or len(number.as_tuple().digits) > 100
            or abs(number.adjusted()) > 300
        ):
            return None
        return number
    if isinstance(value, str) and _NUMERIC_TEXT.fullmatch(value):
        if not declared_numeric and "." not in value and "e" not in value.casefold():
            return None
        try:
            number = Decimal(value)
        except InvalidOperation:
            return None
        if (
            not number.is_finite()
            or len(number.as_tuple().digits) > 100
            or abs(number.adjusted()) > 300
        ):
            return None
        return number
    return None


def _numeric_values(
    values: list[Scalar],
    data_type: str | None,
    column_name: str,
) -> list[Decimal] | None:
    non_null = [value for value in values if value is not None]
    if not non_null:
        return None
    declared_numeric = bool(data_type and _NUMERIC_TYPE.search(data_type))
    if not declared_numeric and _IDENTIFIER_NAMES.search(column_name):
        return None
    converted = [_decimal(value, declared_numeric=declared_numeric) for value in non_null]
    if all(value is not None for value in converted):
        return [value for value in converted if value is not None]
    return None


def _parse_iso_date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    try:
        if len(candidate) == 10:
            parsed_date = date.fromisoformat(candidate)
            return datetime.combine(parsed_date, datetime.min.time())
        parsed_datetime = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        if parsed_datetime.tzinfo is not None:
            parsed_datetime = parsed_datetime.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed_datetime
    except ValueError:
        return None


def _date_values(values: list[Scalar], data_type: str | None) -> list[datetime] | None:
    non_null = [value for value in values if value is not None]
    if not non_null:
        return None
    declared_date = bool(
        data_type
        and any(token in data_type.casefold() for token in ("date", "time", "timestamp"))
    )
    parsed = [_parse_iso_date(value) for value in non_null]
    if all(value is not None for value in parsed) and (
        declared_date or all(isinstance(value, str) and len(value) >= 10 for value in non_null)
    ):
        return [value for value in parsed if value is not None]
    return None


def _distinct_key(value: Scalar) -> tuple[str, str]:
    return type(value).__name__, repr(value)


def _category_frequencies(values: list[Scalar]) -> list[CategoryFrequency]:
    counts: Counter[tuple[str, str]] = Counter()
    originals: dict[tuple[str, str], Scalar] = {}
    for value in values:
        if value is None:
            continue
        key = _distinct_key(value)
        counts[key] += 1
        originals[key] = value
    if not 1 < len(counts) <= min(_MAX_CATEGORY_VALUES, max(2, len(values))):
        return []
    return [
        CategoryFrequency(value=originals[key], count=count)
        for key, count in counts.most_common(_MAX_CATEGORY_VALUES)
    ]


def analyze_execution(result: SQLExecutionResponse) -> AnalyticsSummary:
    if result.status != "success":
        raise ValueError("Analytics require a successful execution result.")

    width = len(result.columns)
    column_values = [
        [row[index] if index < len(row) else None for row in result.rows]
        for index in range(width)
    ]
    numeric_by_index = [
        _numeric_values(values, result.columns[index].data_type, result.columns[index].name)
        for index, values in enumerate(column_values)
    ]
    dates_by_index = [
        _date_values(values, result.columns[index].data_type)
        for index, values in enumerate(column_values)
    ]

    analytics_columns: list[ColumnAnalytics] = []
    numeric_indexes: list[int] = []
    categorical_indexes: list[int] = []
    date_indexes: list[int] = []
    for index, column in enumerate(result.columns):
        values = column_values[index]
        non_null = [value for value in values if value is not None]
        distinct_count = len({_distinct_key(value) for value in non_null})
        numeric_values = numeric_by_index[index]
        date_values = dates_by_index[index]
        frequencies = (
            []
            if numeric_values is not None or date_values is not None
            else _category_frequencies(values)
        )
        stats = None
        if numeric_values:
            numeric_indexes.append(index)
            stats = NumericStatistics(
                minimum=min(numeric_values),
                maximum=max(numeric_values),
                mean=sum(numeric_values) / len(numeric_values),
                median=Decimal(str(median(numeric_values))),
                total=sum(numeric_values),
            )
        elif frequencies:
            categorical_indexes.append(index)

        minimum_date = maximum_date = None
        date_granularity = None
        if date_values:
            date_indexes.append(index)
            minimum_date = min(date_values).isoformat()
            maximum_date = max(date_values).isoformat()
        analytics_columns.append(
            ColumnAnalytics(
                name=column.name,
                data_type=column.data_type,
                non_null_count=len(non_null),
                null_count=len(values) - len(non_null),
                distinct_count=distinct_count,
                numeric_statistics=stats,
                category_frequencies=frequencies,
                date_minimum=minimum_date,
                date_maximum=maximum_date,
                date_granularity=date_granularity,
            )
        )

    trend_pair_count = 0
    for date_index in date_indexes:
        date_values = dates_by_index[date_index] or []
        use_months = len({value.date() for value in date_values}) > 90
        for numeric_index in numeric_indexes:
            trend_pair_count += 1
            if trend_pair_count > _MAX_TREND_PAIRS:
                break
            non_null_pairs: dict[str, list[Decimal]] = defaultdict(list)
            numeric_type = result.columns[numeric_index].data_type
            declared_numeric = bool(numeric_type and _NUMERIC_TYPE.search(numeric_type))
            for row in result.rows:
                date_value = _parse_iso_date(
                    row[date_index] if date_index < len(row) else None
                )
                number = _decimal(
                    row[numeric_index] if numeric_index < len(row) else None,
                    declared_numeric=declared_numeric,
                )
                if date_value is None or number is None:
                    continue
                bucket = (
                    date_value.strftime("%Y-%m")
                    if use_months
                    else date_value.strftime("%Y-%m-%d")
                )
                non_null_pairs[bucket].append(number)
            analytics_columns[date_index].trend.extend(
                TrendPoint(
                    date=bucket,
                    value_column=result.columns[numeric_index].name,
                    total=sum(numbers),
                    average=sum(numbers) / len(numbers),
                    count=len(numbers),
                )
                for bucket, numbers in sorted(non_null_pairs.items())
            )
        if trend_pair_count > _MAX_TREND_PAIRS:
            break
        if analytics_columns[date_index].trend:
            analytics_columns[date_index].date_granularity = (
                "month" if use_months else "day"
            )

    group_pair_count = 0
    for category_index in categorical_indexes:
        for numeric_index in numeric_indexes:
            group_pair_count += 1
            if group_pair_count > _MAX_GROUP_PAIRS:
                break
            groups: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
            group_values: dict[tuple[str, str], Scalar] = {}
            for row in result.rows:
                category = row[category_index] if category_index < len(row) else None
                number = _decimal(
                    row[numeric_index] if numeric_index < len(row) else None,
                    declared_numeric=bool(
                        result.columns[numeric_index].data_type
                        and _NUMERIC_TYPE.search(
                            result.columns[numeric_index].data_type
                        )
                    ),
                )
                if category is not None and number is not None:
                    key = _distinct_key(category)
                    groups[key].append(number)
                    group_values[key] = category
            summaries = sorted(
                groups.items(),
                key=lambda item: sum(item[1]),
                reverse=True,
            )[:_MAX_GROUPS_PER_PAIR]
            analytics_columns[category_index].grouped_summaries.extend(
                GroupSummary(
                    category=group_values[key],
                    value_column=result.columns[numeric_index].name,
                    count=len(numbers),
                    total=sum(numbers),
                    average=sum(numbers) / len(numbers),
                )
                for key, numbers in summaries
            )
        if group_pair_count > _MAX_GROUP_PAIRS:
            break

    observations: list[str] = []
    for column in analytics_columns:
        if column.numeric_statistics is not None:
            observations.append(
                f"{column.name} ranges from {column.numeric_statistics.minimum} "
                f"to {column.numeric_statistics.maximum} across returned rows."
            )
        if column.date_minimum and column.date_maximum:
            observations.append(
                f"{column.name} spans {column.date_minimum} to {column.date_maximum}."
            )
        if column.category_frequencies:
            top = column.category_frequencies[0]
            observations.append(
                f"{column.name} has {column.distinct_count} distinct non-null values; "
                f"{top.value!s} is most frequent ({top.count} rows)."
            )
    if result.truncated:
        observations.append(
            "Statistics describe only the bounded rows returned by this execution."
        )
    if not result.rows:
        observations.append("The execution returned no rows to analyze.")

    return AnalyticsSummary(
        execution_id=result.execution_id,
        row_count=result.row_count,
        column_count=width,
        truncated=result.truncated,
        columns=analytics_columns,
        observations=observations[:20],
    )
