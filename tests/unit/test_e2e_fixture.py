"""Unit tests proving the e2e agent fixture must seed the DB from markdown.

These tests document the root cause of the two e2e failure classes:
- Duplicate entities created instead of updated (DB empty → LLM sees no known_entities → is_new: true → create_entity appends a new section)
- Quest completion ignored (DB empty → known_entities empty → extraction prompt rule "only generate updates for entities in known_entities" fires → no updates extracted)
"""

import pytest
from src.storage.db import NotebookDB
from src.storage.markdown import MarkdownStore
from src.storage.migrate import migrate


@pytest.fixture
def seeded(tmp_path):
    nb = tmp_path / "notebook"
    store = MarkdownStore(nb)
    store.write_file(
        "people.md",
        "---\ntype: characters\ndescription: NPCs\n---\n\n"
        "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n"
        "- Lost the key.\n",
    )
    store.write_file(
        "todos.md",
        "---\ntype: todos\ndescription: Quests\n---\n\n"
        "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n"
        "- The key is at the fishing hab.\n",
    )
    return nb, store


@pytest.mark.unit
class TestDBMustBeSeededFromMarkdown:
    def test_db_empty_before_migrate(self, seeded):
        """Without migrate(), DB has no known entities even though markdown has content."""
        nb, store = seeded
        db = NotebookDB(nb)
        assert db.get_known_entities() == {}

    def test_db_populated_after_migrate(self, seeded):
        """After migrate(), DB reflects the markdown content."""
        nb, store = seeded
        db = NotebookDB(nb)
        migrate(nb, db)

        known = db.get_known_entities()
        assert "Roger" in known.get("characters", [])
        assert "Recover Loadmaster's Key" in known.get("todos", [])

    def test_empty_db_causes_roger_to_look_new(self, seeded):
        """With an empty DB, get_known_entities() returns {} so the extraction
        prompt sees no known characters — Roger appears new to the LLM."""
        nb, store = seeded
        db = NotebookDB(nb)
        known = db.get_known_entities()
        # Roger is not in known_entities → LLM will set is_new: true → duplicate created
        assert "Roger" not in known.get("characters", [])

    def test_migrated_db_shows_roger_as_known(self, seeded):
        """After migrate(), Roger is in known_entities — LLM will not treat him as new."""
        nb, store = seeded
        db = NotebookDB(nb)
        migrate(nb, db)
        known = db.get_known_entities()
        assert "Roger" in known.get("characters", [])

    def test_migrated_db_shows_quest_as_known(self, seeded):
        """After migrate(), the quest is in known_entities — LLM can generate updates for it."""
        nb, store = seeded
        db = NotebookDB(nb)
        migrate(nb, db)
        known = db.get_known_entities()
        assert "Recover Loadmaster's Key" in known.get("todos", [])
