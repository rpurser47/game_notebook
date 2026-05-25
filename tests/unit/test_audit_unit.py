"""Unit tests for NotebookDB integrity audit.

Three classes of issues are detected:
1. status_mismatch  — entities.status disagrees with entity_fields status value
2. cross_type_name  — same entity name exists under two different types
3. multi_match_update — update targets a name present in multiple markdown files

Audit runs sub-100ms (pure SQL + file scan, no LLM).
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.storage.db import NotebookDB
from src.storage.markdown import MarkdownStore
from src.agent.nodes import NodeFactory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_db(tmp_path: Path) -> NotebookDB:
    return NotebookDB(tmp_path / "notebook")


def make_factory(tmp_path: Path) -> tuple[NodeFactory, NotebookDB, MarkdownStore]:
    nb = tmp_path / "notebook"
    db = NotebookDB(nb)
    store = MarkdownStore(nb)
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="Noted.")
    index = MagicMock()
    index.hybrid_search.return_value = []
    return NodeFactory(llm, store, index, db), db, store


# ---------------------------------------------------------------------------
# 1. DB integrity audit — status_mismatch
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAuditStatusMismatch:
    def test_no_issues_on_clean_db(self, tmp_path):
        db = make_db(tmp_path)
        eid = db.insert_entity("Delta", "todos", status="open")
        db.upsert_field(eid, "status", "open")
        issues = db.audit()
        mismatches = [i for i in issues if i["type"] == "status_mismatch"]
        assert mismatches == []

    def test_detects_status_mismatch(self, tmp_path):
        """entities.status disagrees with entity_fields status — should be flagged."""
        db = make_db(tmp_path)
        eid = db.insert_entity("Delta Security Station", "todos", status="open")
        # Manually corrupt: set entity row status without going through upsert_field
        db._conn.execute("UPDATE entities SET status = 'closed' WHERE id = ?", (eid,))
        db._conn.commit()
        # entity_fields still has 'open' from insert_entity
        issues = db.audit()
        mismatches = [i for i in issues if i["type"] == "status_mismatch"]
        assert len(mismatches) == 1
        assert mismatches[0]["entity"] == "Delta Security Station"
        assert mismatches[0]["entities_status"] == "closed"
        assert mismatches[0]["fields_status"] == "open"

    def test_no_mismatch_when_field_absent(self, tmp_path):
        """Entity with no status field and no status column — not a mismatch."""
        db = make_db(tmp_path)
        db.insert_entity("Orphan", "todos")
        issues = db.audit()
        mismatches = [i for i in issues if i["type"] == "status_mismatch"]
        assert mismatches == []

    def test_multiple_mismatches_all_returned(self, tmp_path):
        db = make_db(tmp_path)
        for name in ("Alpha", "Beta"):
            eid = db.insert_entity(name, "todos", status="open")
            db._conn.execute("UPDATE entities SET status = 'closed' WHERE id = ?", (eid,))
        db._conn.commit()
        issues = db.audit()
        mismatches = [i for i in issues if i["type"] == "status_mismatch"]
        assert len(mismatches) == 2


# ---------------------------------------------------------------------------
# 2. DB integrity audit — cross_type_name
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAuditCrossTypeName:
    def test_no_issues_when_names_unique_across_types(self, tmp_path):
        db = make_db(tmp_path)
        db.insert_entity("Kira", "characters")
        db.insert_entity("Sigma Facility", "locations")
        issues = db.audit()
        cross = [i for i in issues if i["type"] == "cross_type_name"]
        assert cross == []

    def test_detects_same_name_in_two_types(self, tmp_path):
        """Same name in both locations and todos — should be flagged."""
        db = make_db(tmp_path)
        db.insert_entity("Delta Security Station", "locations")
        db.insert_entity("Delta Security Station", "todos")
        issues = db.audit()
        cross = [i for i in issues if i["type"] == "cross_type_name"]
        assert len(cross) == 1
        assert cross[0]["entity"] == "Delta Security Station"
        assert set(cross[0]["types"]) == {"locations", "todos"}

    def test_same_name_same_type_not_flagged(self, tmp_path):
        """UNIQUE(name, type) prevents duplicates within a type — not a cross-type issue."""
        db = make_db(tmp_path)
        db.insert_entity("Delta Security Station", "todos")
        db.insert_entity("Delta Security Station", "todos")  # idempotent
        issues = db.audit()
        cross = [i for i in issues if i["type"] == "cross_type_name"]
        assert cross == []


# ---------------------------------------------------------------------------
# 3. Persist — cross-type create warning injected into response state
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCrossTypeCreateWarning:
    def _seed_location(self, store: MarkdownStore, db: NotebookDB) -> None:
        store.write_file(
            "places.md",
            "---\ntype: locations\ndescription: Places\n---\n\n"
            "## Delta Security Station\n**Status:** closed\n",
        )
        store.write_file("todos.md", "---\ntype: todos\ndescription: Quests\n---\n")
        eid = db.insert_entity("Delta Security Station", "locations", status="closed")
        db.upsert_field(eid, "status", "closed")

    def test_cross_type_flag_injected_when_name_exists_in_different_type(self, tmp_path):
        """Creating a todo named 'Delta Security Station' when a location with that name
        exists should set cross_type_warnings in state."""
        factory, db, store = make_factory(tmp_path)
        self._seed_location(store, db)

        state = {
            "intent": "record",
            "user_input": "I need to investigate the Delta Security Station",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [
                {"name": "Delta Security Station", "type": "todos",
                 "is_new": True, "resolved_name": "Delta Security Station", "fields": {}}
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
            "conflicts": [],
        }

        result = factory.persist(state)
        warnings = result.get("cross_type_warnings", [])
        assert len(warnings) == 1
        assert warnings[0]["entity"] == "Delta Security Station"
        assert "locations" in warnings[0]["existing_type"]

    def test_no_warning_when_name_is_unique_across_types(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        store.write_file("todos.md", "---\ntype: todos\ndescription: Quests\n---\n")

        state = {
            "intent": "record",
            "user_input": "I need to find the missing key",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [
                {"name": "Find the Missing Key", "type": "todos",
                 "is_new": True, "resolved_name": "Find the Missing Key", "fields": {}}
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
            "conflicts": [],
        }

        result = factory.persist(state)
        assert result.get("cross_type_warnings", []) == []

    def test_cross_type_warning_surfaced_in_respond_prompt(self, tmp_path):
        """cross_type_warnings in state must appear in the LLM prompt so the response
        asks for confirmation inline."""
        factory, db, store = make_factory(tmp_path)
        self._seed_location(store, db)

        state = {
            "intent": "record",
            "user_input": "I need to investigate the Delta Security Station",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [
                {"name": "Delta Security Station", "type": "todos",
                 "is_new": True, "resolved_name": "Delta Security Station", "fields": {}}
            ],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
            "conflicts": [],
            "cross_type_warnings": [
                {"entity": "Delta Security Station", "existing_type": "locations", "new_type": "todos"}
            ],
        }

        factory.respond(state)
        prompt = factory.llm.invoke.call_args[0][0][-1].content
        assert "Delta Security Station" in prompt
        assert "location" in prompt.lower() or "locations" in prompt.lower()


# ---------------------------------------------------------------------------
# 4. Persist — multi-match update (name exists in multiple files)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMultiMatchUpdate:
    def _seed_both_files(self, store: MarkdownStore, db: NotebookDB) -> None:
        store.write_file(
            "places.md",
            "---\ntype: locations\ndescription: Places\n---\n\n"
            "## Delta Security Station\n**Status:** closed\n",
        )
        store.write_file(
            "todos.md",
            "---\ntype: todos\ndescription: Quests\n---\n\n"
            "## Delta Security Station\n**Subtype:** mystery\n**Status:** open\n",
        )
        db.insert_entity("Delta Security Station", "locations", status="closed")
        db.insert_entity("Delta Security Station", "todos", status="open")

    def test_find_entity_files_returns_all_matches(self, tmp_path):
        """_find_entity_files (plural) should return all files containing the entity."""
        factory, db, store = make_factory(tmp_path)
        self._seed_both_files(store, db)
        files = factory._find_entity_files("Delta Security Station")
        assert "places.md" in files
        assert "todos.md" in files

    def test_find_entity_files_returns_single_match_as_list(self, tmp_path):
        factory, db, store = make_factory(tmp_path)
        store.write_file(
            "todos.md",
            "---\ntype: todos\ndescription: Quests\n---\n\n"
            "## Find the Key\n**Status:** open\n",
        )
        db.insert_entity("Find the Key", "todos", status="open")
        files = factory._find_entity_files("Find the Key")
        assert files == ["todos.md"]

    def test_multi_match_update_sets_ambiguity_flag(self, tmp_path):
        """When an update targets a name present in multiple files, persist must
        skip the write and set update_ambiguities in state."""
        factory, db, store = make_factory(tmp_path)
        self._seed_both_files(store, db)

        state = {
            "intent": "update",
            "user_input": "close out Delta Security Station",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Delta Security Station", "field": "status",
                 "old_value": "", "new_value": "completed"}
            ],
            "extracted_relationships": [],
            "files_modified": [],
            "conflicts": [],
        }

        result = factory.persist(state)
        ambiguities = result.get("update_ambiguities", [])
        assert len(ambiguities) == 1
        assert ambiguities[0]["entity"] == "Delta Security Station"
        assert set(ambiguities[0]["files"]) == {"places.md", "todos.md"}

    def test_multi_match_update_does_not_write(self, tmp_path):
        """The write must be skipped when ambiguous — neither file should change."""
        factory, db, store = make_factory(tmp_path)
        self._seed_both_files(store, db)

        original_todos = store.read_file("todos.md")

        state = {
            "intent": "update",
            "user_input": "close out Delta Security Station",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Delta Security Station", "field": "status",
                 "old_value": "", "new_value": "completed"}
            ],
            "extracted_relationships": [],
            "files_modified": [],
            "conflicts": [],
        }

        factory.persist(state)
        assert store.read_file("todos.md") == original_todos

    def test_ambiguity_surfaced_in_respond_prompt(self, tmp_path):
        """update_ambiguities in state must appear in the LLM prompt so the response
        asks the player which entity they mean."""
        factory, db, store = make_factory(tmp_path)
        self._seed_both_files(store, db)

        state = {
            "intent": "update",
            "user_input": "close out Delta Security Station",
            "messages": [],
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [],
            "extracted_relationships": [],
            "files_modified": [],
            "conflicts": [],
            "update_ambiguities": [
                {"entity": "Delta Security Station",
                 "files": ["places.md", "todos.md"],
                 "field": "status", "new_value": "completed"}
            ],
        }

        factory.respond(state)
        prompt = factory.llm.invoke.call_args[0][0][-1].content
        assert "Delta Security Station" in prompt
        assert "place" in prompt.lower() or "todo" in prompt.lower() or "location" in prompt.lower()
