from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.query_history import QueryHistory
    from app.db.models.saved_query import SavedQuery
    from app.db.models.user import User


class DatabaseConnection(Base):
    __tablename__ = "database_connections"
    __table_args__ = (
        CheckConstraint(
            "database_type IN ('sqlite', 'postgresql')",
            name="ck_database_connections_database_type",
        ),
        Index("ix_database_connections_user_id", "user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    database_type: Mapped[str] = mapped_column(String(16), nullable=False)
    connection_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_succeeded: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="database_connections")
    query_history: Mapped[list["QueryHistory"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
    saved_queries: Mapped[list["SavedQuery"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan"
    )
