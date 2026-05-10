"""Unit tests for the respond node's contextual enrichment behaviour."""

import json
import pytest
from unittest.mock import MagicMock, call
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


@pytest.mark.unit
class TestRespondContextualEnrichment:
    def test_respond_fetches_related_context_for_record_intent(self):
        """For a record intent, respond should call hybrid_search to fetch
        context about entities that were just recorded."""
        factory = make_factory()
        factory.index.hybrid_search.return_value = [
            make_chunk("Simone Parker", "## Simone Parker\n**Location:** Crew Quarters C\n")
        ]

        state = {
            "intent": "record",
            "user_input": "Got a key card from Simone Parker, who is dead in the bunker room",
            "messages": [],
            "extracted_observations": ["Found key card from Simone Parker"],
            "resolved_entities": [
                {"name": "Simone Parker", "type": "character", "is_new": False,
                 "resolved_name": "Simone Parker", "fields": {}}
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)
        factory.index.hybrid_search.assert_called()

    def test_respond_fetches_related_context_for_update_intent(self):
        """For an update intent, respond should call hybrid_search to fetch
        context about the entities that were updated."""
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
        """For a chat intent, no index lookup should happen."""
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
        """The content of retrieved related chunks should appear in the prompt
        sent to the LLM so it can reference it in the response."""
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
            "resolved_entities": [
                {"name": "Simone Parker", "type": "character", "is_new": False,
                 "resolved_name": "Simone Parker", "fields": {}}
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
        }

        factory.respond(state)

        # Inspect the prompt actually sent to the LLM
        call_args = factory.llm.invoke.call_args
        prompt_messages = call_args[0][0]
        full_prompt = " ".join(m.content for m in prompt_messages)
        assert "Crew Quarters C" in full_prompt
