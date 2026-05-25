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

    # Conflict detection (proposed updates that contradict DB state)
    conflicts: list[dict]

    # Integrity warnings (cross-type name collision, multi-match update ambiguity)
    cross_type_warnings: list[dict]
    update_ambiguities: list[dict]

    # Query analysis
    query_filters: dict | None
    semantic_query: str | None

    # Retrieved context — structured (DB) and semantic (vector)
    structured_results: list[dict]
    retrieved_chunks: list[dict]

    # Output
    response: str
    files_modified: list[str]

    # Error handling
    error: str | None
