"""Unit tests for NodeFactory nodes — focused on the reflect node."""

import json
import pytest
from unittest.mock import MagicMock
from src.agent.nodes import NodeFactory


def make_factory(response_text: str) -> NodeFactory:
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=response_text)
    store = MagicMock()
    index = MagicMock()
    db = MagicMock()
    return NodeFactory(llm, store, index, db)


def make_chunks(names: list[str], entity_type: str = "items") -> list[dict]:
    return [
        {
            "chunk_id": f"things.md::{name}",
            "content": f"## {name}\n**Category:** misc\n",
            "metadata": {"entity_name": name, "entity_type": entity_type},
        }
        for name in names
    ]


# ---------------------------------------------------------------------------
# reflect node — unit tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestReflectNode:
    def test_keeps_relevant_chunks(self):
        """LLM says both chunks are relevant — both pass through."""
        chunks = make_chunks(["Surface Hab Storage Code", "Epsilon Storage Room Code"])
        relevant_ids = [c["chunk_id"] for c in chunks]
        factory = make_factory(json.dumps({"relevant_ids": relevant_ids}))

        state = {"user_input": "what needs a code?", "retrieved_chunks": chunks}
        result = factory.reflect(state)

        assert len(result["retrieved_chunks"]) == 2

    def test_removes_irrelevant_chunks(self):
        """LLM flags Rig #1 as irrelevant to a codes query — it should be dropped."""
        chunks = make_chunks(["Surface Hab Storage Code", "Rig #1"])
        relevant_ids = ["things.md::Surface Hab Storage Code"]
        factory = make_factory(json.dumps({"relevant_ids": relevant_ids}))

        state = {"user_input": "what needs a code?", "retrieved_chunks": chunks}
        result = factory.reflect(state)

        names = [c["metadata"]["entity_name"] for c in result["retrieved_chunks"]]
        assert "Surface Hab Storage Code" in names
        assert "Rig #1" not in names

    def test_empty_chunks_returns_empty_without_llm_call(self):
        """No chunks to filter — skip the LLM call entirely."""
        factory = make_factory("{}")
        state = {"user_input": "what needs a code?", "retrieved_chunks": []}
        result = factory.reflect(state)

        factory.llm.invoke.assert_not_called()
        assert result["retrieved_chunks"] == []

    def test_all_chunks_irrelevant_returns_empty(self):
        """LLM returns no relevant IDs — result is empty list."""
        chunks = make_chunks(["Rig #1", "Rig #3", "Mk2 Cargo Drone"])
        factory = make_factory(json.dumps({"relevant_ids": []}))

        state = {"user_input": "what needs a code?", "retrieved_chunks": chunks}
        result = factory.reflect(state)

        assert result["retrieved_chunks"] == []

    def test_malformed_llm_response_passes_chunks_through(self):
        """If the LLM returns unparseable JSON, pass all chunks through rather than dropping data."""
        chunks = make_chunks(["Surface Hab Storage Code", "Epsilon Storage Room Code"])
        factory = make_factory("sorry, I cannot help with that")

        state = {"user_input": "what needs a code?", "retrieved_chunks": chunks}
        result = factory.reflect(state)

        assert len(result["retrieved_chunks"]) == 2

    def test_unknown_ids_in_llm_response_are_ignored(self):
        """LLM hallucinating a chunk ID that doesn't exist should not crash or add phantom results."""
        chunks = make_chunks(["Surface Hab Storage Code"])
        factory = make_factory(json.dumps({"relevant_ids": [
            "things.md::Surface Hab Storage Code",
            "things.md::DOES_NOT_EXIST",
        ]}))

        state = {"user_input": "what needs a code?", "retrieved_chunks": chunks}
        result = factory.reflect(state)

        assert len(result["retrieved_chunks"]) == 1
        assert result["retrieved_chunks"][0]["metadata"]["entity_name"] == "Surface Hab Storage Code"

    def test_preserves_chunk_content_unchanged(self):
        """Reflect should not mutate chunk data, only filter."""
        chunks = make_chunks(["Surface Hab Storage Code"])
        relevant_ids = ["things.md::Surface Hab Storage Code"]
        factory = make_factory(json.dumps({"relevant_ids": relevant_ids}))

        state = {"user_input": "what needs a code?", "retrieved_chunks": chunks}
        result = factory.reflect(state)

        assert result["retrieved_chunks"][0] == chunks[0]
