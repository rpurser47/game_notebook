"""State schema for the notebook agent."""

from typing import Literal, TypedDict

from langchain_core.messages import BaseMessage


class NotebookState(TypedDict, total=False):
    """State for the notebook agent graph."""

    # Conversation history
    messages: list[BaseMessage]

    # Current user input
    user_input: str

    # Intent classification
    intent: Literal["record", "query", "update", "chat"] | None

    # Extraction results
    extracted_observations: list[str]
    extracted_entities: list[dict]
    extracted_updates: list[dict]
    extracted_relationships: list[dict]

    # Resolved entities (after coreference)
    resolved_entities: list[dict]

    # Query analysis
    query_filters: dict | None
    semantic_query: str | None

    # Retrieved context
    retrieved_chunks: list[dict]

    # Output
    response: str
    files_modified: list[str]

    # Error handling
    error: str | None
