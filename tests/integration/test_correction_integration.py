"""Integration tests: full correction flow — DB + markdown + index all updated.

These tests wire real DB, MarkdownStore, and NotebookIndex together (no LLM)
and drive the persist node directly to verify that a player correction is
reflected consistently across all three storage layers.
"""

import pytest
from pathlib import Path

from src.storage.db import NotebookDB
from src.storage.markdown import MarkdownStore
from src.storage.index import NotebookIndex
from src.agent.nodes import NodeFactory
from unittest.mock import MagicMock


@pytest.fixture
def stack(tmp_path):
    """Real DB + MarkdownStore + NotebookIndex wired together."""
    nb = tmp_path / "notebook"
    db = NotebookDB(nb)
    store = MarkdownStore(nb)
    index = NotebookIndex(nb, embedding_provider="local")
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="Noted.")
    factory = NodeFactory(llm, store, index, db)
    return factory, db, store, index


def _seed_roger(store, db):
    store.write_file(
        "people.md",
        "---\ntype: characters\ndescription: NPCs\n---\n\n"
        "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n"
        "- Lost the key.\n",
    )
    eid = db.insert_entity("Roger", "characters")
    db.upsert_field(eid, "role", "Loadmaster", source="narrator")
    return eid


def _seed_quest(store, db):
    store.write_file(
        "todos.md",
        "---\ntype: todos\ndescription: Quests\n---\n\n"
        "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n"
        "- The key is at the fishing hab.\n",
    )
    eid = db.insert_entity("Recover Loadmaster's Key", "todos")
    db.upsert_field(eid, "status", "open", source="narrator")
    return eid


@pytest.mark.integration
class TestCorrectionAllLayersUpdated:
    def test_db_updated_after_correction(self, stack):
        factory, db, store, index = stack
        _seed_roger(store, db)

        factory.persist({
            "intent": "update",
            "user_input": "Actually Roger is the captain, not the loadmaster",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Loadmaster", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        })

        assert db.get_field("Roger", "role") == "Captain"

    def test_markdown_updated_after_correction(self, stack):
        factory, db, store, index = stack
        _seed_roger(store, db)

        factory.persist({
            "intent": "update",
            "user_input": "Actually Roger is the captain",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Loadmaster", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        })

        content = store.read_file("people.md")
        idx = content.find("## Roger")
        section = content[idx: idx + 300]
        assert "**Role:** Captain" in section
        assert "**Role:** Loadmaster" not in section

    def test_index_updated_after_correction(self, stack):
        factory, db, store, index = stack
        roger_id = _seed_roger(store, db)
        index.index_file(store, "people.md")

        factory.persist({
            "intent": "update",
            "user_input": "Actually Roger is the captain",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Loadmaster", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        })

        results = index.search("Captain", top_k=5)
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Roger" in names

    def test_index_no_longer_returns_old_value_after_correction(self, stack):
        """After updating Roger's role, searching for Loadmaster should not return Roger."""
        factory, db, store, index = stack
        _seed_roger(store, db)
        index.index_file(store, "people.md")

        factory.persist({
            "intent": "update",
            "user_input": "Actually Roger is the captain",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Loadmaster", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        })

        results = index.search("Loadmaster", top_k=5)
        for r in results:
            if r["metadata"]["entity_name"] == "Roger":
                assert "Loadmaster" not in r["content"], (
                    "Roger's indexed content still contains old role 'Loadmaster' after correction"
                )

    def test_facts_log_records_correction_provenance(self, stack):
        """The facts table must have an entry with old_value=Loadmaster, new_value=Captain."""
        factory, db, store, index = stack
        eid = _seed_roger(store, db)

        factory.persist({
            "intent": "update",
            "user_input": "Actually Roger is the captain",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Loadmaster", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        })

        rows = db._conn.execute(
            "SELECT old_value, new_value, source FROM facts "
            "WHERE entity_id = ? AND field = 'role' ORDER BY id",
            (eid,)
        ).fetchall()
        correction = rows[-1]
        assert correction["old_value"] == "Loadmaster"
        assert correction["new_value"] == "Captain"

    def test_db_and_markdown_agree_after_correction(self, stack):
        """DB canonical value and markdown bold field must match after a correction."""
        factory, db, store, index = stack
        _seed_roger(store, db)

        factory.persist({
            "intent": "update",
            "user_input": "Actually Roger is the captain",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Loadmaster", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        })

        db_val = db.get_field("Roger", "role")
        md_content = store.read_file("people.md")
        assert f"**Role:** {db_val}" in md_content


@pytest.mark.integration
class TestQuestCompletionAllLayersUpdated:
    def test_db_status_updated_on_completion(self, stack):
        factory, db, store, index = stack
        eid = _seed_quest(store, db)

        factory.persist({
            "intent": "update",
            "user_input": "I recovered the Loadmaster's Key",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Recover Loadmaster's Key", "field": "status",
                 "old_value": "open", "new_value": "completed"},
            ],
            "extracted_relationships": [],
        })

        entity = db.get_entity_by_name("Recover Loadmaster's Key")
        assert entity.status == "completed"

    def test_markdown_status_updated_on_completion(self, stack):
        factory, db, store, index = stack
        _seed_quest(store, db)

        factory.persist({
            "intent": "update",
            "user_input": "I recovered the Loadmaster's Key",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Recover Loadmaster's Key", "field": "status",
                 "old_value": "open", "new_value": "completed"},
            ],
            "extracted_relationships": [],
        })

        content = store.read_file("todos.md")
        idx = content.find("## Recover Loadmaster's Key")
        section = content[idx: idx + 300]
        assert "completed" in section.lower()

    def test_outcome_written_to_db_on_completion(self, stack):
        factory, db, store, index = stack
        _seed_quest(store, db)

        factory.persist({
            "intent": "update",
            "user_input": "I recovered the Loadmaster's Key at Sorrell's fishing hab",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Recover Loadmaster's Key", "field": "status",
                 "old_value": "open", "new_value": "completed"},
            ],
            "extracted_relationships": [],
        })

        outcome = db.get_field("Recover Loadmaster's Key", "outcome")
        assert outcome is not None

    def test_outcome_written_to_markdown_on_completion(self, stack):
        factory, db, store, index = stack
        _seed_quest(store, db)

        factory.persist({
            "intent": "update",
            "user_input": "I recovered the Loadmaster's Key at Sorrell's fishing hab",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Recover Loadmaster's Key", "field": "status",
                 "old_value": "open", "new_value": "completed"},
            ],
            "extracted_relationships": [],
        })

        content = store.read_file("todos.md")
        idx = content.find("## Recover Loadmaster's Key")
        section = content[idx: idx + 400]
        assert "**Outcome:**" in section

    def test_index_reflects_completed_status(self, stack):
        factory, db, store, index = stack
        _seed_quest(store, db)
        index.index_file(store, "todos.md")

        factory.persist({
            "intent": "update",
            "user_input": "I recovered the Loadmaster's Key",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Recover Loadmaster's Key", "field": "status",
                 "old_value": "open", "new_value": "completed"},
            ],
            "extracted_relationships": [],
        })

        # After completion, an open-quest filter should not return it
        results = index.hybrid_search(
            filters={"entity_type": "todos", "status": "open"},
            top_k=10,
        )
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Recover Loadmaster's Key" not in names


@pytest.mark.integration
class TestNewEntityAllLayersPopulated:
    def test_new_entity_searchable_immediately_after_record(self, stack):
        """After persist, the new entity must be findable via semantic search."""
        factory, db, store, index = stack
        store.write_file("people.md", "---\ntype: characters\ndescription: NPCs\n---\n\n")

        factory.persist({
            "intent": "record",
            "user_input": "I met a blacksmith named Kira in Millhaven",
            "extracted_observations": [],
            "resolved_entities": [
                {"name": "Kira", "type": "character", "is_new": True,
                 "resolved_name": "Kira", "fields": {"role": "blacksmith"}},
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
        })

        results = index.search("blacksmith", top_k=5)
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Kira" in names

    def test_new_entity_in_db_and_markdown_consistent(self, stack):
        factory, db, store, index = stack
        store.write_file("people.md", "---\ntype: characters\ndescription: NPCs\n---\n\n")

        factory.persist({
            "intent": "record",
            "user_input": "Met Kira the blacksmith",
            "extracted_observations": [],
            "resolved_entities": [
                {"name": "Kira", "type": "character", "is_new": True,
                 "resolved_name": "Kira", "fields": {"role": "blacksmith"}},
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
        })

        db_entity = db.get_entity_by_name("Kira")
        assert db_entity is not None
        assert db_entity.fields.get("role") == "blacksmith"

        md_content = store.read_file("people.md")
        assert "## Kira" in md_content
