"""Unit tests for MarkdownStore."""

import pytest
from src.storage.markdown import MarkdownStore


@pytest.mark.unit
class TestCreateEntity:
    def test_creates_header_and_role(self, store):
        store.write_file("people.md", "---\ntype: characters\ndescription: NPCs\n---\n\n")
        store.create_entity("people.md", "Kira", "character", {"role": "blacksmith"})
        content = store.read_file("people.md")
        assert "## Kira" in content
        assert "**Role:** blacksmith" in content

    def test_creates_location_with_explored(self, store):
        store.write_file("places.md", "---\ntype: locations\ndescription: Places\n---\n\n")
        store.create_entity("places.md", "Millhaven", "location", {"explored": "partial"})
        content = store.read_file("places.md")
        assert "## Millhaven" in content
        assert "**Explored:** partial" in content

    def test_creates_todo_with_subtype_and_default_status(self, store):
        store.write_file("todos.md", "---\ntype: todos\ndescription: Quests\n---\n\n")
        store.create_entity("todos.md", "Find the Key", "todo", {"subtype": "quest"})
        content = store.read_file("todos.md")
        assert "## Find the Key" in content
        assert "**Subtype:** quest" in content
        assert "**Status:** open" in content

    def test_appends_to_existing_file(self, seeded_store):
        seeded_store.create_entity("people.md", "Yuki", "character", {"role": "mechanic"})
        content = seeded_store.read_file("people.md")
        assert "## Roger" in content
        assert "## Yuki" in content


@pytest.mark.unit
class TestUpdateEntity:
    def test_updates_field_in_place(self, seeded_store):
        seeded_store.update_entity("people.md", "Roger", {"Role": "Captain"})
        content = seeded_store.read_file("people.md")
        assert "**Role:** Captain" in content
        assert "**Role:** Loadmaster" not in content

    def test_returns_false_for_missing_entity(self, seeded_store):
        result = seeded_store.update_entity("people.md", "NonExistent", {"Role": "test"})
        assert result is False

    def test_appends_history_entry(self, seeded_store):
        seeded_store.update_entity(
            "people.md", "Roger", {}, append_history="Turned out to be the captain."
        )
        content = seeded_store.read_file("people.md")
        assert "### " in content
        assert "Turned out to be the captain." in content

    def test_no_duplicate_entity_on_update(self, seeded_store):
        seeded_store.update_entity("people.md", "Roger", {"Role": "Captain"})
        content = seeded_store.read_file("people.md")
        assert content.count("## Roger") == 1


@pytest.mark.unit
class TestAppendToJournal:
    def test_adds_session_header(self, seeded_store):
        seeded_store.append_to_journal(["Found the key at the fishing hab."])
        content = seeded_store.read_file("journal.md")
        assert "## Session —" in content
        assert "Found the key at the fishing hab." in content

    def test_appends_multiple_observations(self, seeded_store):
        seeded_store.append_to_journal(["Obs one.", "Obs two.", "Obs three."])
        content = seeded_store.read_file("journal.md")
        assert "- Obs one." in content
        assert "- Obs two." in content
        assert "- Obs three." in content

    def test_preserves_existing_journal_content(self, seeded_store):
        seeded_store.append_to_journal(["New entry."])
        content = seeded_store.read_file("journal.md")
        assert "## Session — initial" in content
        assert "## Session —" in content
        assert content.index("initial") < content.index("New entry.")

    def test_creates_journal_if_missing(self, store):
        store.append_to_journal(["First ever entry."])
        content = store.read_file("journal.md")
        assert "First ever entry." in content


@pytest.mark.unit
class TestParseIntoChunks:
    def test_one_chunk_per_entity(self, seeded_store):
        chunks = seeded_store.parse_into_chunks("people.md")
        names = [c.entity_name for c in chunks]
        assert "Roger" in names

    def test_chunk_has_correct_type(self, seeded_store):
        chunks = seeded_store.parse_into_chunks("people.md")
        assert all(c.entity_type == "characters" for c in chunks)

    def test_chunk_parses_status(self, seeded_store):
        chunks = seeded_store.parse_into_chunks("people.md")
        roger = next(c for c in chunks if c.entity_name == "Roger")
        assert roger.status == "unknown"

    def test_chunk_parses_related(self, seeded_store):
        chunks = seeded_store.parse_into_chunks("people.md")
        roger = next(c for c in chunks if c.entity_name == "Roger")
        assert "Loadmaster's Key" in roger.related

    def test_empty_file_returns_no_chunks(self, store):
        store.write_file("empty.md", "---\ntype: characters\ndescription: empty\n---\n\n")
        chunks = store.parse_into_chunks("empty.md")
        assert chunks == []

    def test_missing_file_returns_no_chunks(self, store):
        chunks = store.parse_into_chunks("nonexistent.md")
        assert chunks == []


@pytest.mark.unit
class TestGetKnownEntities:
    def test_returns_entities_grouped_by_type(self, seeded_store):
        known = seeded_store.get_known_entities()
        assert "characters" in known
        assert "Roger" in known["characters"]

    def test_includes_multiple_files(self, seeded_store):
        known = seeded_store.get_known_entities()
        assert "characters" in known
        assert "todos" in known

    def test_empty_notebook_returns_empty_dict(self, store):
        known = store.get_known_entities()
        assert known == {}
