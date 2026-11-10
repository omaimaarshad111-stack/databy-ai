from typing import Literal

from langchain_groq import ChatGroq
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings


class IntentClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal[
        "database_query",
        "schema_question",
        "general_question",
        "clarification_needed",
        "unsupported_request",
    ]
    user_facing_message: str = Field(min_length=1, max_length=1000)


class UserFacingAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=2000)


def classify_intent(
    question: str,
    conversation_context: list[dict[str, str]],
) -> IntentClassification:
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("AI service is not configured. Set GROQ_API_KEY.")

    model = ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0,
        timeout=settings.groq_timeout_seconds,
        max_retries=0,
    ).with_structured_output(IntentClassification)
    history = "\n".join(
        f"{message['role']}: {message['content'][:1000]}"
        for message in conversation_context[-8:]
    )
    return model.invoke(
        [
            (
                "system",
                "Classify the latest request for a read-only database assistant. "
                "Use database_query only when the user asks for information that "
                "requires querying connected data. Use schema_question for schema "
                "or table exploration. Use general_question for a safe, relevant "
                "question that needs no connected-data query. Use clarification_needed "
                "when essential information is ambiguous. Use unsupported_request "
                "for writes, administrative actions, or unrelated requests. "
                "Never classify an instruction to modify data as a read query. "
                "Return only a brief user-facing status message, not private reasoning."
            ),
            (
                "human",
                f"Recent conversation:\n{history or '[none]'}\n\n"
                f"Latest request:\n{question}",
            ),
        ]
    )


def answer_general_question(
    question: str,
    conversation_context: list[dict[str, str]],
) -> str:
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("AI service is not configured. Set GROQ_API_KEY.")
    model = ChatGroq(
        model=settings.groq_model,
        api_key=settings.groq_api_key,
        temperature=0,
        timeout=settings.groq_timeout_seconds,
        max_retries=0,
    ).with_structured_output(UserFacingAnswer)
    history = "\n".join(
        f"{message['role']}: {message['content'][:1000]}"
        for message in conversation_context[-8:]
    )
    result = model.invoke(
        [
            (
                "system",
                "Answer the user's safe, general question briefly. This is a read-only "
                "database assistant. Do not claim to have accessed or queried a database. "
                "Do not reveal private reasoning. Only use the provided conversation.",
            ),
            (
                "human",
                f"Recent conversation:\n{history or '[none]'}\n\n"
                f"Question:\n{question}",
            ),
        ]
    )
    return result.answer
