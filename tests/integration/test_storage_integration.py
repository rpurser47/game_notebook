"""Integration tests: MarkdownStore + NotebookIndex working together."""

import pytest
from src.storage.markdown import MarkdownStore
from src.storage.index import NotebookIndex


@pytest.fixture
def store(tmp_path):
    return MarkdownStore(tmp_path / "notebook")


@pytest.fixture
def index(tmp_path):
    return NotebookIndex(tmp_path / "notebook", embedding_provider="local")


@pytest.fixture
def store_and_index(tmp_path):
    nb = tmp_path / "notebook"
    return MarkdownStore(nb), NotebookIndex(nb, embedding_provider="local")


# ---------------------------------------------------------------------------
# Write → index → search round-trips
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestNewEntityIsSearchable:
    def test_character_found_by_role(self, store_and_index):
        store, idx = store_and_index
        store.write_file("people.md", "---\ntype: characters\ndescription: NPCs\n---\n\n")
        store.create_entity("people.md", "Kira", "character", {"role": "blacksmith"})
        idx.index_file(store, "people.md")

        results = idx.search("blacksmith", top_k=5)
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Kira" in names

    def test_location_found_by_name(self, store_and_index):
        store, idx = store_and_index
        store.write_file("places.md", "---\ntype: locations\ndescription: Places\n---\n\n")
        store.create_entity("places.md", "Millhaven", "location", {"explored": "partial"})
        idx.index_file(store, "places.md")

        results = idx.search("Millhaven", top_k=5)
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Millhaven" in names

    def test_journal_entry_is_searchable(self, store_and_index):
        store, idx = store_and_index
        store.write_file("journal.md", "---\ntype: observations\ndescription: Journal\n---\n\n")
        store.append_to_journal(["Found the Loadmaster's key at the fishing hab."])
        idx.index_file(store, "journal.md")

        results = idx.search("fishing hab key", top_k=5)
        assert len(results) > 0
        assert any("fishing hab" in r["content"] for r in results)


@pytest.mark.integration
class TestUpdatedEntityReflectsInIndex:
    def test_updated_field_appears_in_search(self, store_and_index):
        store, idx = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n- Lost the key.\n",
        )
        idx.index_file(store, "people.md")

        store.update_entity("people.md", "Roger", {"Role": "Captain"})
        idx.index_file(store, "people.md")

        results = idx.search("Captain", top_k=5)
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Roger" in names

    def test_old_content_superseded_after_update(self, store_and_index):
        store, idx = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n- Lost the key.\n",
        )
        idx.index_file(store, "people.md")
        store.update_entity("people.md", "Roger", {"Role": "Captain"})
        idx.index_file(store, "people.md")

        # Fetch the stored document directly and confirm it reflects the update
        results = idx.search("Roger", top_k=5)
        roger = next((r for r in results if r["metadata"]["entity_name"] == "Roger"), None)
        assert roger is not None
        assert "Captain" in roger["content"]
        assert "**Role:** Loadmaster" not in roger["content"]


# ---------------------------------------------------------------------------
# Metadata filtering
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMetadataFilters:
    def _seed(self, store, idx):
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Kira\n**Role:** blacksmith\n**Status:** active\n\n"
            "## Roger\n**Role:** loadmaster\n**Status:** unknown\n\n",
        )
        store.write_file(
            "todos.md",
            "---\ntype: todos\ndescription: Quests\n---\n\n"
            "## Find the Key\n**Subtype:** quest\n**Status:** open\n\n"
            "## Repair Reactor\n**Subtype:** quest\n**Status:** completed\n\n",
        )
        idx.index_file(store, "people.md")
        idx.index_file(store, "todos.md")

    def test_filter_by_entity_type_returns_only_that_type(self, store_and_index):
        store, idx = store_and_index
        self._seed(store, idx)

        results = idx.hybrid_search(filters={"entity_type": "characters"}, top_k=10)
        types = {r["metadata"]["entity_type"] for r in results}
        assert types == {"characters"}

    def test_filter_by_status_open_excludes_completed(self, store_and_index):
        store, idx = store_and_index
        self._seed(store, idx)

        results = idx.hybrid_search(filters={"entity_type": "todos", "status": "open"}, top_k=10)
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Find the Key" in names
        assert "Repair Reactor" not in names

    def test_semantic_plus_type_filter(self, store_and_index):
        store, idx = store_and_index
        self._seed(store, idx)

        results = idx.hybrid_search(
            semantic_query="blacksmith metalworker",
            filters={"entity_type": "characters"},
            top_k=5,
        )
        types = {r["metadata"]["entity_type"] for r in results}
        assert "todos" not in types


# ---------------------------------------------------------------------------
# Hash-based incremental indexing
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestIncrementalIndexing:
    def test_unchanged_file_returns_zero_updates(self, store_and_index):
        store, idx = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Kira\n**Role:** blacksmith\n\n",
        )
        idx.index_file(store, "people.md")
        second_pass = idx.index_file(store, "people.md")
        assert second_pass == 0

    def test_changed_file_returns_nonzero_updates(self, store_and_index):
        store, idx = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Kira\n**Role:** blacksmith\n\n",
        )
        idx.index_file(store, "people.md")
        store.update_entity("people.md", "Kira", {"Role": "Captain"})
        second_pass = idx.index_file(store, "people.md")
        assert second_pass > 0

    def test_stats_reflect_indexed_chunks(self, store_and_index):
        store, idx = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Kira\n**Role:** blacksmith\n\n"
            "## Roger\n**Role:** loadmaster\n\n",
        )
        idx.index_file(store, "people.md")
        stats = idx.get_stats()
        assert stats["total_chunks"] == 2
        assert stats["tracked_hashes"] == 2


# ---------------------------------------------------------------------------
# Orphan removal
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestOrphanRemoval:
    def test_deleted_entity_removed_from_index(self, store_and_index):
        store, idx = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Kira\n**Role:** blacksmith\n\n"
            "## Roger\n**Role:** loadmaster\n\n",
        )
        idx.index_all(store)

        # Remove Roger from the file
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Kira\n**Role:** blacksmith\n\n",
        )
        idx.index_all(store)

        stats = idx.get_stats()
        assert stats["total_chunks"] == 1

        results = idx.search("Roger loadmaster", top_k=5)
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Roger" not in names
