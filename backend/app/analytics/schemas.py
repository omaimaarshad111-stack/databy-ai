from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ChartType = Literal["bar", "line", "pie", "area", "scatter"]
ChartValue = str | int | float | bool | None


class NumericStatistics(BaseModel):
    minimum: Decimal
    maximum: Decimal
    mean: Decimal
    median: Decimal
    total: Decimal


class CategoryFrequency(BaseModel):
    value: ChartValue
    count: int


class TrendPoint(BaseModel):
    date: str
    value_column: str
    total: Decimal
    average: Decimal
    count: int


class GroupSummary(BaseModel):
    category: ChartValue
    value_column: str
    count: int
    total: Decimal
    average: Decimal


class ColumnAnalytics(BaseModel):
    name: str
    data_type: str | None
    non_null_count: int
    null_count: int
    distinct_count: int
    numeric_statistics: NumericStatistics | None = None
    category_frequencies: list[CategoryFrequency] = Field(default_factory=list)
    date_minimum: str | None = None
    date_maximum: str | None = None
    date_granularity: Literal["day", "month"] | None = None
    trend: list[TrendPoint] = Field(default_factory=list)
    grouped_summaries: list[GroupSummary] = Field(default_factory=list)


class AnalyticsSummary(BaseModel):
    execution_id: UUID
    row_count: int
    column_count: int
    truncated: bool
    columns: list[ColumnAnalytics]
    observations: list[str] = Field(default_factory=list)


class ChartRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chart_type: ChartType
    title: str
    x_axis_column: str
    y_axis_column: str
    grouping_column: str | None = None
    explanation: str
    required_data_fields: list[str]
    suitable: bool
    suitability_reason: str
    data: list[dict[str, ChartValue]]


class ChartRecommendationsResponse(BaseModel):
    execution_id: UUID
    suitable: bool
    reason: str | None = None
    recommendations: list[ChartRecommendation]


class AnalyticsFollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=2000)


class AnalyticsFollowUpResponse(BaseModel):
    execution_id: UUID
    answer: str
    source: Literal["cached_result"]
