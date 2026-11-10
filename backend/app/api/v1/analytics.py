import csv
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.analytics.schemas import (
    AnalyticsFollowUpRequest,
    AnalyticsFollowUpResponse,
    AnalyticsSummary,
    ChartRecommendationsResponse,
)
from app.analytics.service import (
    ExecutionResultsExpiredError,
    ExecutionResultsUnavailableError,
    UnsupportedAnalyticsFollowUpError,
    answer_analytics_follow_up,
    export_result_csv,
    get_analytics_summary,
    get_chart_recommendations,
    get_owned_execution_result,
)
from app.api.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_db
from app.sql.execution_service import ExecutionNotFoundError
from app.sql.schemas import SQLExecutionResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/executions", tags=["Analytics"])


def _execution_or_http_error(
    db: Session,
    user: User,
    execution_id: UUID,
) -> SQLExecutionResponse:
    try:
        return get_owned_execution_result(db, user, execution_id)
    except ExecutionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found.",
        ) from None
    except ExecutionResultsExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="The result window expired. Run the query again to analyze or export it.",
        ) from None
    except ExecutionResultsUnavailableError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A successful result window is not available for this execution.",
        ) from None


@router.get("/{execution_id}/analytics", response_model=AnalyticsSummary)
def execution_analytics(
    execution_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AnalyticsSummary:
    result = _execution_or_http_error(db, current_user, execution_id)
    try:
        return get_analytics_summary(result)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Analytics are unavailable for this execution result.",
        ) from None


@router.get(
    "/{execution_id}/charts",
    response_model=ChartRecommendationsResponse,
)
def execution_charts(
    execution_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChartRecommendationsResponse:
    result = _execution_or_http_error(db, current_user, execution_id)
    try:
        return get_chart_recommendations(result)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chart recommendations are unavailable for this execution result.",
        ) from None


@router.get("/{execution_id}/export/csv")
def export_execution_csv(
    execution_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    result = _execution_or_http_error(db, current_user, execution_id)
    try:
        content = export_result_csv(result)
    except (csv.Error, UnicodeError) as exc:
        logger.warning("CSV result export failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The result could not be exported.",
        ) from None
    return Response(
        content=content.encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="databy-ai-{execution_id}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/{execution_id}/analytics/follow-up",
    response_model=AnalyticsFollowUpResponse,
)
def execution_analytics_follow_up(
    execution_id: UUID,
    request: AnalyticsFollowUpRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AnalyticsFollowUpResponse:
    result = _execution_or_http_error(db, current_user, execution_id)
    try:
        return answer_analytics_follow_up(result, request.question.strip())
    except UnsupportedAnalyticsFollowUpError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from None
