"""Unit tests for the respond node's contextual enrichment and LLM-driven question behaviour."""

import json
import pytest
from unittest.mock import MagicMock
from src.agent.nodes import NodeFactory


def make_factory(response_text: str = "Noted.") -> NodeFactory:
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=response_text)
    store = MagicMock()
    index = MagicMock()
    db = MagicMock()
    db.get_entity_by_name.return_value = None
    return NodeFactory(llm, store, index, db)


def make_chunk(name: str, content: str, entity_type: str = "characters") -> dict:
    return {
        "chunk_id": f"people.md::{name}",
        "content": content,
        "metadata": {"entity_name": name, "entity_type": entity_type},
    }


def _prompt_text(factory: NodeFactory) -> str:
    """Return the full concatenated text of all messages sent to the LLM."""
    call_args = factory.llm.invoke.call_args
    return " ".join(m.content for m in call_args[0][0])


def _new_entity(name: str, entity_type: str = "character", fields: dict | None = None) -> dict:
    return {
        "name": name,
        "type": entity_type,
        "is_new": True,
        "resolved_name": name,
        "fields": fields or {},
    }


def _existing_entity(name: str) -> dict:
    return {
        "name": name,
        "type": "character",
        "is_new": False,
        "resolved_name": name,
        "fields": {"role": "captain"},
    }


# ---------------------------------------------------------------------------
# Contextual enrichment — existing behaviour preserved
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRespondContextualEnrichment:
    def test_respond_fetches_related_context_for_record_intent(self):
        factory = make_factory()
        factory.index.hybrid_search.return_value = [
            make_chunk("Simone Parker", "## Simone Parker\n**Location:** Crew Quarters C\n")
        ]

        state = {
            "intent": "record",
            "user_input": "Got a key card from Simone Parker, who is dead in the bunker room",
            "messages": [],
            "extracted_observations": ["Found key card from Simone Parker"],
            "resolved_entities": [_existing_entity("Simone Parker")],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        factory.index.hybrid_search.assert_called()

    def test_respond_fetches_related_context_for_update_intent(self):
        factory = make_factory()
        factory.index.hybrid_search.return_value = [
            make_chunk(
                "Unlock Epsilon Secure Storage",
                "## Unlock Epsilon Secure Storage\n**Status:** open\n",
                entity_type="todos",
            )
        ]

        state = {
            "intent": "update",
            "user_input": "I recovered the Loadmaster's Key",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Recover Loadmaster's Key", "field": "Status",
                 "old_value": "open", "new_value": "completed"}
            ],
            "extracted_relationships": [],
            "files_modified": ["todos.md"],
        }

        factory.respond(state)
        factory.index.hybrid_search.assert_called()

    def test_respond_does_not_fetch_context_for_chat_intent(self):
        factory = make_factory()

        state = {
            "intent": "chat",
            "user_input": "Thanks!",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        factory.index.hybrid_search.assert_not_called()

    def test_related_context_included_in_llm_prompt(self):
        factory = make_factory()
        factory.index.hybrid_search.return_value = [
            make_chunk(
                "Simone Parker",
                "## Simone Parker\n**Location:** Crew Quarters C\n- Resident of Crew Quarters C.",
            )
        ]

        state = {
            "intent": "record",
            "user_input": "Got a key card from Simone Parker",
            "messages": [],
            "extracted_observations": ["Found key card from Simone Parker"],
            "resolved_entities": [_existing_entity("Simone Parker")],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        assert "Crew Quarters C" in _prompt_text(factory)


# ---------------------------------------------------------------------------
# LLM-driven clarifying question — new behaviour
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRespondLLMQuestion:
    def test_new_entity_name_included_in_prompt(self):
        """When a new entity is recorded, its name appears in the prompt so the
        LLM can decide whether to ask a question."""
        factory = make_factory()
        factory.index.hybrid_search.return_value = []

        state = {
            "intent": "record",
            "user_input": "I met a guard named Praxis outside the Theta gate",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [_new_entity("Praxis")],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        assert "Praxis" in _prompt_text(factory)

    def test_new_entity_fields_included_in_prompt(self):
        """Extracted fields for a new entity are surfaced so the LLM knows what
        is already known before deciding whether to ask."""
        factory = make_factory()
        factory.index.hybrid_search.return_value = []

        state = {
            "intent": "record",
            "user_input": "Met an engineer called Sven, he works in the reactor room",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [_new_entity("Sven", fields={"role": "engineer", "location": "reactor room"})],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        prompt = _prompt_text(factory)
        assert "engineer" in prompt
        assert "reactor room" in prompt

    def test_consequential_gap_instruction_present_for_new_entities(self):
        """The 'consequential fact' instruction must be present when a new entity
        is in the state so the LLM knows it may ask one question."""
        factory = make_factory()
        factory.index.hybrid_search.return_value = []

        state = {
            "intent": "record",
            "user_input": "There's a person called the Warden",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [_new_entity("the Warden")],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        assert "consequential" in _prompt_text(factory)

    def test_no_question_instruction_for_existing_entities_only(self):
        """When all resolved entities are existing (is_new=False), the clarifying
        question instruction must NOT be injected — the LLM shouldn't be nudged
        to ask about things already in the notebook."""
        factory = make_factory()
        factory.index.hybrid_search.return_value = []

        state = {
            "intent": "record",
            "user_input": "Spoke to Roger again",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [_existing_entity("Roger")],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        assert "consequential" not in _prompt_text(factory)

    def test_no_question_instruction_for_update_intent(self):
        """Updates never trigger the new-entity question instruction."""
        factory = make_factory()
        factory.index.hybrid_search.return_value = []

        state = {
            "intent": "update",
            "user_input": "Mark the Theta quest as complete",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [_new_entity("Theta quest")],
            "extracted_updates": [{"entity": "Theta quest", "field": "status", "new_value": "completed"}],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        assert "consequential" not in _prompt_text(factory)

    def test_no_question_instruction_for_chat_intent(self):
        """Chat turns never trigger the new-entity question instruction."""
        factory = make_factory()

        state = {
            "intent": "chat",
            "user_input": "Hello",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        assert "consequential" not in _prompt_text(factory)

    def test_multiple_new_entities_all_listed_in_prompt(self):
        """All new entities are listed so the LLM has full context when deciding
        whether to ask a single question."""
        factory = make_factory()
        factory.index.hybrid_search.return_value = []

        state = {
            "intent": "record",
            "user_input": "Met Praxis and the Warden near the gate",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [_new_entity("Praxis"), _new_entity("the Warden")],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        prompt = _prompt_text(factory)
        assert "Praxis" in prompt
        assert "the Warden" in prompt

    def test_llm_response_returned_as_is(self):
        """The respond node returns whatever the LLM produces — it doesn't
        post-process or strip trailing questions."""
        factory = make_factory("Noted Praxis. Is he with the mining crew or a guard for hire?")
        factory.index.hybrid_search.return_value = []

        state = {
            "intent": "record",
            "user_input": "Met a guard named Praxis",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [_new_entity("Praxis")],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        result = factory.respond(state)
        assert result["response"] == "Noted Praxis. Is he with the mining crew or a guard for hire?"
