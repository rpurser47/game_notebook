"""Unit tests for NodeFactory.persist and NodeFactory.conflict_check nodes.

These nodes are the heart of the write path — persist must update both
DB and markdown consistently, and conflict_check must gate writes correctly.
All LLM calls are mocked; DB and MarkdownStore use real in-memory/tmp instances.
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.storage.db import NotebookDB
from src.storage.markdown import MarkdownStore
from src.agent.nodes import NodeFactory


def make_factory(tmp_path: Path, llm_response: str = "Noted.") -> tuple[NodeFactory, NotebookDB, MarkdownStore]:
    """Return a NodeFactory wired to real DB + MarkdownStore, with mocked LLM and index."""
    nb = tmp_path / "notebook"
    db = NotebookDB(nb)
    store = MarkdownStore(nb)
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=llm_response)
    index = MagicMock()
    index.hybrid_search.return_value = []
    factory = NodeFactory(llm, store, index, db)
    return factory, db, store


def _seed_people(store: MarkdownStore) -> None:
    store.write_file(
        "people.md",
        "---\ntype: characters\ndescription: NPCs\n---\n\n"
        "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n"
        "- Lost the key.\n",
    )


def _seed_todos(store: MarkdownStore) -> None:
    store.write_file(
        "todos.md",
        "---\ntype: todos\ndescription: Quests\n---\n\n"
        "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n"
        "- The key is probably at the fishing hab.\n",
    )


# ---------------------------------------------------------------------------
# conflict_check node
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConflictCheckNode:
    def test_no_conflicts_when_no_updates(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        state = {"extracted_updates": []}
        result = factory.conflict_check(state)
        assert result["conflicts"] == []

    def test_no_conflict_for_routine_update_empty_old_value(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")

        state = {
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "", "new_value": "Captain"},
            ]
        }
        result = factory.conflict_check(state)
        assert result["conflicts"] == []

    def test_conflict_detected_when_explicit_old_value_is_wrong(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")

        state = {
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Captain", "new_value": "Pilot"},
            ]
        }
        result = factory.conflict_check(state)
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["entity"] == "Roger"
        assert result["conflicts"][0]["db_value"] == "Loadmaster"

    def test_conflict_check_passes_through_existing_state(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        state = {
            "extracted_updates": [],
            "intent": "update",
            "user_input": "test",
        }
        result = factory.conflict_check(state)
        assert result["intent"] == "update"
        assert result["user_input"] == "test"


# ---------------------------------------------------------------------------
# persist node — new entities written to both DB and markdown
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPersistNewEntity:
    def test_new_character_written_to_db(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        store.write_file("people.md", "---\ntype: characters\ndescription: NPCs\n---\n\n")

        state = {
            "intent": "record",
            "user_input": "I met a blacksmith named Kira in Millhaven",
            "extracted_observations": [],
            "resolved_entities": [
                {"name": "Kira", "type": "character", "is_new": True,
                 "resolved_name": "Kira", "fields": {"role": "blacksmith"}},
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
        }
        factory.persist(state)

        entity = db.get_entity_by_name("Kira")
        assert entity is not None
        assert entity.type == "characters"
        assert entity.fields.get("role") == "blacksmith"

    def test_new_character_written_to_markdown(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        store.write_file("people.md", "---\ntype: characters\ndescription: NPCs\n---\n\n")

        state = {
            "intent": "record",
            "user_input": "Met Kira",
            "extracted_observations": [],
            "resolved_entities": [
                {"name": "Kira", "type": "character", "is_new": True,
                 "resolved_name": "Kira", "fields": {"role": "blacksmith"}},
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
        }
        factory.persist(state)

        content = store.read_file("people.md")
        assert "## Kira" in content

    def test_existing_entity_not_duplicated_in_db(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        _seed_people(store)
        db.insert_entity("Roger", "characters")

        state = {
            "intent": "record",
            "user_input": "Roger is the loadmaster",
            "extracted_observations": [],
            "resolved_entities": [
                {"name": "Roger", "type": "character", "is_new": False,
                 "resolved_name": "Roger", "fields": {}},
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
        }
        factory.persist(state)

        count = db._conn.execute(
            "SELECT COUNT(*) FROM entities WHERE lower(name) = 'roger'"
        ).fetchone()[0]
        assert count == 1

    def test_observations_written_to_journal(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        store.write_file(
            "journal.md",
            "---\ntype: observations\ndescription: Journal\n---\n\n# Journal\n\n"
        )

        state = {
            "intent": "record",
            "user_input": "Found a key at the fishing hab",
            "extracted_observations": ["Found a key at the fishing hab."],
            "resolved_entities": [],
            "extracted_updates": [],
            "extracted_relationships": [],
        }
        factory.persist(state)

        content = store.read_file("journal.md")
        assert "fishing hab" in content

    def test_observations_not_written_for_update_intent(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        store.write_file(
            "journal.md",
            "---\ntype: observations\ndescription: Journal\n---\n\n# Journal\n\n"
        )

        state = {
            "intent": "update",
            "user_input": "Actually Roger is the captain",
            "extracted_observations": ["Roger is the captain."],
            "resolved_entities": [],
            "extracted_updates": [],
            "extracted_relationships": [],
        }
        factory.persist(state)

        content = store.read_file("journal.md")
        assert "Roger is the captain" not in content

    def test_files_modified_returned(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        store.write_file("people.md", "---\ntype: characters\ndescription: NPCs\n---\n\n")

        state = {
            "intent": "record",
            "user_input": "Met Kira",
            "extracted_observations": [],
            "resolved_entities": [
                {"name": "Kira", "type": "character", "is_new": True,
                 "resolved_name": "Kira", "fields": {}},
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
        }
        result = factory.persist(state)
        assert "people.md" in result["files_modified"]


# ---------------------------------------------------------------------------
# persist node — field updates written to both DB and markdown
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPersistFieldUpdate:
    def test_correction_updates_db_field(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        _seed_people(store)
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")

        state = {
            "intent": "update",
            "user_input": "Actually Roger is the captain, not the loadmaster",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Loadmaster", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        }
        factory.persist(state)

        assert db.get_field("Roger", "role") == "Captain"

    def test_correction_updates_markdown(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        _seed_people(store)
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")

        state = {
            "intent": "update",
            "user_input": "Actually Roger is the captain",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Loadmaster", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        }
        factory.persist(state)

        content = store.read_file("people.md")
        idx = content.find("## Roger")
        section = content[idx: idx + 300]
        assert "Captain" in section
        assert "**Role:** Loadmaster" not in section

    def test_correction_writes_facts_log_with_old_value(self, tmp_path):
        """The facts table must record the old value when a correction is made."""
        factory, db, store = make_factory(tmp_path)
        _seed_people(store)
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")

        state = {
            "intent": "update",
            "user_input": "Actually Roger is the captain",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Loadmaster", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        }
        factory.persist(state)

        rows = db._conn.execute(
            "SELECT old_value, new_value FROM facts WHERE entity_id = ? AND field = 'role' ORDER BY id",
            (eid,)
        ).fetchall()
        assert len(rows) == 2
        assert rows[-1]["old_value"] == "Loadmaster"
        assert rows[-1]["new_value"] == "Captain"

    def test_correction_stores_turn_text_in_facts(self, tmp_path):
        """The player's exact input should be preserved in the facts log."""
        factory, db, store = make_factory(tmp_path)
        _seed_people(store)
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")

        turn = "Actually Roger is the captain, not the loadmaster"
        state = {
            "intent": "update",
            "user_input": turn,
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Roger", "field": "role", "old_value": "Loadmaster", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        }
        factory.persist(state)

        row = db._conn.execute(
            "SELECT turn_text FROM facts WHERE entity_id = ? AND field = 'role' ORDER BY id DESC LIMIT 1",
            (eid,)
        ).fetchone()
        assert row["turn_text"] == turn

    def test_status_update_syncs_entity_row_status(self, tmp_path):
        """Updating status via persist must also update entities.status column."""
        factory, db, store = make_factory(tmp_path)
        _seed_todos(store)
        eid = db.insert_entity("Recover Loadmaster's Key", "todos")
        db.upsert_field(eid, "status", "open")

        state = {
            "intent": "update",
            "user_input": "I recovered the Loadmaster's Key",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Recover Loadmaster's Key", "field": "status",
                 "old_value": "open", "new_value": "completed"},
            ],
            "extracted_relationships": [],
        }
        factory.persist(state)

        entity = db.get_entity_by_name("Recover Loadmaster's Key")
        assert entity.status == "completed"

    def test_completing_todo_writes_outcome_to_markdown(self, tmp_path):
        """When a todo is marked completed, an Outcome field must appear in markdown."""
        factory, db, store = make_factory(tmp_path)
        _seed_todos(store)
        eid = db.insert_entity("Recover Loadmaster's Key", "todos")
        db.upsert_field(eid, "status", "open")

        turn = "I recovered the Loadmaster's Key at Sorrell's fishing hab"
        state = {
            "intent": "update",
            "user_input": turn,
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Recover Loadmaster's Key", "field": "status",
                 "old_value": "open", "new_value": "completed"},
            ],
            "extracted_relationships": [],
        }
        factory.persist(state)

        content = store.read_file("todos.md")
        idx = content.find("## Recover Loadmaster's Key")
        section = content[idx: idx + 400]
        assert "**Outcome:**" in section

    def test_completing_todo_writes_outcome_to_db(self, tmp_path):
        """Outcome must also be persisted to the DB facts log, not just markdown."""
        factory, db, store = make_factory(tmp_path)
        _seed_todos(store)
        eid = db.insert_entity("Recover Loadmaster's Key", "todos")
        db.upsert_field(eid, "status", "open")

        state = {
            "intent": "update",
            "user_input": "I recovered the Loadmaster's Key",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Recover Loadmaster's Key", "field": "status",
                 "old_value": "open", "new_value": "completed"},
            ],
            "extracted_relationships": [],
        }
        factory.persist(state)

        outcome = db.get_field("Recover Loadmaster's Key", "outcome")
        assert outcome is not None
        assert len(outcome) > 0

    def test_unknown_entity_update_skipped_gracefully(self, tmp_path):
        """An update referencing an entity not in DB should not crash."""
        factory, db, store = make_factory(tmp_path)

        state = {
            "intent": "update",
            "user_input": "Actually Nobody is the captain",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Nobody", "field": "role", "old_value": "", "new_value": "Captain"},
            ],
            "extracted_relationships": [],
        }
        result = factory.persist(state)
        assert "files_modified" in result


# ---------------------------------------------------------------------------
# persist node — relationship writes
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPersistRelationships:
    def test_relationship_written_to_db(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        _seed_people(store)
        eid = db.insert_entity("Roger", "characters")

        state = {
            "intent": "record",
            "user_input": "Roger is connected to Kira",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [],
            "extracted_relationships": [
                {"from": "Roger", "to": "Kira", "relation": "knows"},
            ],
        }
        factory.persist(state)

        rels = db.get_relationships(eid)
        assert any(r["to_name"] == "Kira" for r in rels)

    def test_relationship_with_unknown_entity_skipped(self, tmp_path):
        """from_name not in DB — should not crash."""
        factory, db, store = make_factory(tmp_path)

        state = {
            "intent": "record",
            "user_input": "Ghost knows Kira",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [],
            "extracted_relationships": [
                {"from": "Ghost", "to": "Kira", "relation": "knows"},
            ],
        }
        result = factory.persist(state)
        assert "files_modified" in result


# ---------------------------------------------------------------------------
# persist node — index re-indexed after write
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestPersistTriggersReindex:
    def test_index_file_called_for_each_modified_file(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        store.write_file("people.md", "---\ntype: characters\ndescription: NPCs\n---\n\n")
        store.write_file(
            "journal.md",
            "---\ntype: observations\ndescription: Journal\n---\n\n# Journal\n\n"
        )

        state = {
            "intent": "record",
            "user_input": "I met Kira and found a clue",
            "extracted_observations": ["Found a clue."],
            "resolved_entities": [
                {"name": "Kira", "type": "character", "is_new": True,
                 "resolved_name": "Kira", "fields": {}},
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
        }
        factory.persist(state)

        called_files = [call[0][1] for call in factory.index.index_file.call_args_list]
        assert "people.md" in called_files
        assert "journal.md" in called_files

    def test_index_not_called_when_nothing_modified(self, tmp_path):
        factory, db, store = make_factory(tmp_path)

        state = {
            "intent": "update",
            "user_input": "Nothing happened",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [],
            "extracted_relationships": [],
        }
        factory.persist(state)

        factory.index.index_file.assert_not_called()
