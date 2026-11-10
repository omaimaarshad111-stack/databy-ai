from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.database_targets.exceptions import ConnectionNotFoundError
from app.db.models import DatabaseConnection, QueryHistory, SavedQuery, User
from app.db.session import get_db
from app.schemas.workspace import (
    QueryHistoryItem,
    QueryHistoryPage,
    SavedQueryInput,
    SavedQueryResponse,
    SavedQueryUpdate,
)
from app.services.connection_service import get_owned_connection

router = APIRouter(tags=["workspace"])


def _saved_query_response(
    saved_query: SavedQuery,
    connection: DatabaseConnection,
) -> SavedQueryResponse:
    return SavedQueryResponse(
        id=saved_query.id,
        connection_id=connection.id,
        connection_name=connection.name,
        database_type=connection.database_type,
        name=saved_query.name,
        description=saved_query.description,
        sql_query=saved_query.sql_query,
        created_at=saved_query.created_at,
        updated_at=saved_query.updated_at,
    )


@router.get("/history", response_model=QueryHistoryPage)
def list_query_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=200)] = None,
    execution_status: Annotated[
        Literal["pending", "succeeded", "failed", "cancelled"] | None,
        Query(alias="status"),
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> QueryHistoryPage:
    filters = [
        QueryHistory.user_id == current_user.id,
        DatabaseConnection.user_id == current_user.id,
    ]
    if execution_status:
        filters.append(QueryHistory.execution_status == execution_status)
    if search and search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                QueryHistory.natural_language_question.ilike(term),
                QueryHistory.generated_sql.ilike(term),
                DatabaseConnection.name.ilike(term),
            )
        )

    total = db.scalar(
        select(func.count(QueryHistory.id))
        .join(DatabaseConnection, DatabaseConnection.id == QueryHistory.connection_id)
        .where(*filters)
    ) or 0
    records = db.execute(
        select(QueryHistory, DatabaseConnection)
        .join(DatabaseConnection, DatabaseConnection.id == QueryHistory.connection_id)
        .where(*filters)
        .order_by(QueryHistory.created_at.desc(), QueryHistory.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return QueryHistoryPage(
        items=[
            QueryHistoryItem(
                id=history.id,
                connection_id=connection.id,
                connection_name=connection.name,
                database_type=connection.database_type,
                conversation_id=history.conversation_id,
                natural_language_question=history.natural_language_question,
                generated_sql=history.generated_sql,
                execution_status=history.execution_status,
                execution_duration_ms=(
                    history.execution_duration * 1000
                    if history.execution_duration is not None
                    else None
                ),
                created_at=history.created_at,
            )
            for history, connection in records
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/saved-queries", response_model=list[SavedQueryResponse])
def list_saved_queries(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> list[SavedQueryResponse]:
    statement = (
        select(SavedQuery, DatabaseConnection)
        .join(DatabaseConnection, DatabaseConnection.id == SavedQuery.connection_id)
        .where(
            SavedQuery.user_id == current_user.id,
            DatabaseConnection.user_id == current_user.id,
        )
    )
    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(
                SavedQuery.name.ilike(term),
                SavedQuery.description.ilike(term),
                SavedQuery.sql_query.ilike(term),
                DatabaseConnection.name.ilike(term),
            )
        )
    records = db.execute(
        statement.order_by(SavedQuery.updated_at.desc(), SavedQuery.id.desc()).limit(200)
    ).all()
    return [
        _saved_query_response(saved_query, connection)
        for saved_query, connection in records
    ]


@router.post(
    "/saved-queries",
    response_model=SavedQueryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_saved_query(
    request: SavedQueryInput,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SavedQueryResponse:
    try:
        connection = get_owned_connection(db, current_user, request.connection_id)
    except ConnectionNotFoundError:
        raise HTTPException(status_code=404, detail="Database connection not found.") from None
    saved_query = SavedQuery(
        id=uuid4(),
        user_id=current_user.id,
        connection_id=connection.id,
        name=request.name,
        description=request.description,
        sql_query=request.sql_query,
    )
    db.add(saved_query)
    db.commit()
    db.refresh(saved_query)
    return _saved_query_response(saved_query, connection)


@router.patch("/saved-queries/{saved_query_id}", response_model=SavedQueryResponse)
def update_saved_query(
    saved_query_id: UUID,
    request: SavedQueryUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SavedQueryResponse:
    saved_query = db.scalar(
        select(SavedQuery).where(
            SavedQuery.id == saved_query_id,
            SavedQuery.user_id == current_user.id,
        )
    )
    if saved_query is None:
        raise HTTPException(status_code=404, detail="Saved query not found.")

    changes = request.model_dump(exclude_unset=True)
    if any(
        field in changes and changes[field] is None
        for field in ("connection_id", "name", "sql_query")
    ):
        raise HTTPException(
            status_code=422,
            detail="Connection, name, and SQL cannot be cleared.",
        )
    connection_id = request.connection_id or saved_query.connection_id
    try:
        connection = get_owned_connection(db, current_user, connection_id)
    except ConnectionNotFoundError:
        raise HTTPException(status_code=404, detail="Database connection not found.") from None

    for field in ("connection_id", "name", "description", "sql_query"):
        if field in changes:
            setattr(saved_query, field, changes[field])
    db.add(saved_query)
    db.commit()
    db.refresh(saved_query)
    return _saved_query_response(saved_query, connection)


@router.delete(
    "/saved-queries/{saved_query_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_saved_query(
    saved_query_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    saved_query = db.scalar(
        select(SavedQuery).where(
            SavedQuery.id == saved_query_id,
            SavedQuery.user_id == current_user.id,
        )
    )
    if saved_query is None:
        raise HTTPException(status_code=404, detail="Saved query not found.")
    db.delete(saved_query)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
