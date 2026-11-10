import json
import logging
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.nodes.workflow import assistant_graph
from app.agent.schemas import (
    AssistantCompletion,
    AssistantMessageRequest,
    ConversationCreate,
    ConversationDetailResponse,
    ConversationMessageResponse,
    ConversationResponse,
)
from app.agent.state import AssistantState
from app.api.dependencies import get_current_user
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.services.connection_service import get_owned_connection
from app.database_targets.exceptions import ConnectionNotFoundError
from app.sql.schemas import SQLExecutionResponse
from app.sql.schemas import SQLGenerationResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/assistant", tags=["AI assistant"])
MAX_CONTEXT_MESSAGES = 12
MAX_CONTEXT_CHARS = 6000


def _owned_conversation(db: Session, user: User, conversation_id: UUID) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return conversation


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    request: ConversationCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Conversation:
    conversation = Conversation(
        user_id=current_user.id,
        title=request.title.strip() or "New conversation",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[Conversation]:
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.user_id == current_user.id)
            .order_by(Conversation.updated_at.desc())
            .limit(100)
        )
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
)
def get_conversation(
    conversation_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConversationDetailResponse:
    conversation = _owned_conversation(db, current_user, conversation_id)
    messages = list(
        db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(200)
        )
    )
    messages.reverse()
    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[
            ConversationMessageResponse.model_validate(message)
            for message in messages
        ],
    )


def _recent_context(db: Session, conversation_id: UUID) -> list[dict[str, str]]:
    messages = list(
        db.scalars(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role == "user",
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(MAX_CONTEXT_MESSAGES)
        )
    )
    context: list[dict[str, str]] = []
    characters = 0
    for message in reversed(messages):
        content = message.content[:1000]
        if characters + len(content) > MAX_CONTEXT_CHARS:
            break
        context.append({"role": message.role, "content": content})
        characters += len(content)
    return context


def _event(event_name: str, payload: dict[str, object]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, default=str)}\n\n"


def _completion(
    conversation_id: UUID,
    message: Message,
    state: dict[str, object],
    workflow_status: str,
) -> AssistantCompletion:
    generation = state.get("generation")
    execution = state.get("execution")
    validation_errors = state.get("validation_errors", [])
    validation_status = (
        "valid"
        if isinstance(generation, SQLGenerationResponse)
        and generation.status == "success"
        and not validation_errors
        else "invalid"
        if validation_errors
        else "not_run"
    )
    return AssistantCompletion(
        conversation_id=conversation_id,
        message=ConversationMessageResponse.model_validate(message),
        intent=state.get("intent"),
        steps=state.get("steps", []),
        generated_sql=state.get("sql_query"),
        validation_status=validation_status,
        validation_errors=validation_errors,
        execution=execution if isinstance(execution, SQLExecutionResponse) else None,
        workflow_status="completed" if workflow_status == "completed" else "failed",
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=None,
)
def send_message(
    conversation_id: UUID,
    request: AssistantMessageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> StreamingResponse:
    conversation = _owned_conversation(db, current_user, conversation_id)
    try:
        get_owned_connection(db, current_user, request.connection_id)
    except ConnectionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Database connection not found.",
        ) from None

    question = request.content.strip()
    if len(question) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Message must contain at least 3 non-whitespace characters.",
        )
    context = _recent_context(db, conversation_id)
    user_message = Message(
        id=uuid4(),
        conversation_id=conversation_id,
        role="user",
        content=question,
        created_at=datetime.now(UTC),
    )
    db.add(user_message)
    if conversation.title == "New conversation":
        conversation.title = question[:80]
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(user_message)

    initial_state: AssistantState = {
        "db": db,
        "user": current_user,
        "conversation_id": conversation_id,
        "connection_id": request.connection_id,
        "question": question,
        "conversation_context": context,
        "steps": [],
    }

    def stream() -> Generator[str, None, None]:
        state: dict[str, object] = initial_state
        sent_steps = 0
        try:
            for current_state in assistant_graph.stream(
                initial_state,
                stream_mode="values",
            ):
                state = current_state
                steps = current_state.get("steps", [])
                if len(steps) > sent_steps:
                    step = steps[-1]
                    sent_steps = len(steps)
                    yield _event("progress", step)
        except Exception as exc:
            logger.warning("Assistant workflow failed (%s).", type(exc).__name__)
            db.rollback()
            failure_step = {
                "name": "workflow",
                "status": "failed",
                "message": "The request could not be completed.",
            }
            state = {
                "workflow_status": "failed",
                "answer": "The assistant could not complete this request. Please try again.",
                "steps": [failure_step],
            }
            yield _event("progress", failure_step)

        answer = str(
            state.get("answer", "The assistant could not complete this request.")
        )
        assistant_message = Message(
            id=uuid4(),
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            created_at=datetime.now(UTC),
        )
        db.add(assistant_message)
        conversation.updated_at = datetime.now(UTC)
        try:
            db.commit()
            db.refresh(assistant_message)
            completion = _completion(
                conversation_id,
                assistant_message,
                state,
                str(state.get("workflow_status", "failed")),
            )
            yield _event("complete", completion.model_dump(mode="json"))
        except Exception as exc:
            logger.error("Assistant response persistence failed (%s).", type(exc).__name__)
            db.rollback()
            yield _event(
                "error",
                {"message": "The response could not be saved. Please retry."},
            )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
