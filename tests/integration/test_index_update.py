"""Integration tests: embedding correctness after updates.

Verifies that after a field correction or status change, the ChromaDB
collection holds the right document text, right metadata, and right
hash state — not stale data from the pre-update embedding.

All tests use real NotebookIndex (local sentence-transformers) and
real MarkdownStore. No LLM.
"""

import pytest
from src.storage.markdown import MarkdownStore
from src.storage.index import NotebookIndex


@pytest.fixture
def store_and_index(tmp_path):
    nb = tmp_path / "notebook"
    store = MarkdownStore(nb)
    index = NotebookIndex(nb, embedding_provider="local")
    return store, index


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_chunk_direct(index: NotebookIndex, chunk_id: str) -> dict | None:
    """Fetch a chunk directly from ChromaDB by its ID (bypasses semantic search)."""
    result = index.collection.get(
        ids=[chunk_id],
        include=["documents", "metadatas"],
    )
    if not result["ids"]:
        return None
    return {
        "chunk_id": result["ids"][0],
        "content": result["documents"][0],
        "metadata": result["metadatas"][0],
    }


# ---------------------------------------------------------------------------
# Document content after field update
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestDocumentContentAfterUpdate:
    def test_stored_document_reflects_new_field_value(self, store_and_index):
        """The raw document stored in ChromaDB must contain the new field value
        after a re-index, not the original value."""
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n"
            "- Lost the key.\n",
        )
        index.index_file(store, "people.md")

        store.update_entity("people.md", "Roger", {"Role": "Captain"})
        index.index_file(store, "people.md")

        chunk = _get_chunk_direct(index, "people.md::Roger")
        assert chunk is not None, "Roger chunk not found in index"
        assert "Captain" in chunk["content"], (
            f"Expected 'Captain' in stored document but got:\n{chunk['content']}"
        )

    def test_old_field_value_absent_from_stored_document(self, store_and_index):
        """After a correction, the old value must be gone from the stored document."""
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n"
            "- Lost the key.\n",
        )
        index.index_file(store, "people.md")

        store.update_entity("people.md", "Roger", {"Role": "Captain"})
        index.index_file(store, "people.md")

        chunk = _get_chunk_direct(index, "people.md::Roger")
        assert chunk is not None
        assert "**Role:** Loadmaster" not in chunk["content"], (
            "Old role 'Loadmaster' still present in stored document after correction"
        )

    def test_multiple_field_updates_all_reflected(self, store_and_index):
        """Updating two fields at once: both must appear in the stored document."""
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Location:** Unknown\n**Status:** unknown\n\n",
        )
        index.index_file(store, "people.md")

        store.update_entity("people.md", "Roger", {"Role": "Captain", "Location": "Bridge"})
        index.index_file(store, "people.md")

        chunk = _get_chunk_direct(index, "people.md::Roger")
        assert chunk is not None
        assert "Captain" in chunk["content"]
        assert "Bridge" in chunk["content"]
        assert "**Role:** Loadmaster" not in chunk["content"]
        assert "**Location:** Unknown" not in chunk["content"]

    def test_completed_status_reflected_in_stored_document(self, store_and_index):
        """After marking a quest complete, the stored document must say 'completed'."""
        store, index = store_and_index
        store.write_file(
            "todos.md",
            "---\ntype: todos\ndescription: Quests\n---\n\n"
            "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n"
            "- The key is at the fishing hab.\n",
        )
        index.index_file(store, "todos.md")

        store.update_entity("todos.md", "Recover Loadmaster's Key", {"Status": "completed"})
        index.index_file(store, "todos.md")

        chunk = _get_chunk_direct(index, "todos.md::Recover Loadmaster's Key")
        assert chunk is not None
        assert "completed" in chunk["content"].lower(), (
            f"Expected 'completed' in stored document but got:\n{chunk['content']}"
        )
        assert "**Status:** open" not in chunk["content"], (
            "Old status 'open' still in stored document after completion"
        )


# ---------------------------------------------------------------------------
# Metadata correctness after update
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMetadataAfterUpdate:
    def test_status_metadata_updated_after_completion(self, store_and_index):
        """The 'status' metadata field in ChromaDB must be updated when the
        markdown status changes — this is what metadata filters query against."""
        store, index = store_and_index
        store.write_file(
            "todos.md",
            "---\ntype: todos\ndescription: Quests\n---\n\n"
            "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n",
        )
        index.index_file(store, "todos.md")

        store.update_entity("todos.md", "Recover Loadmaster's Key", {"Status": "completed"})
        index.index_file(store, "todos.md")

        chunk = _get_chunk_direct(index, "todos.md::Recover Loadmaster's Key")
        assert chunk is not None
        assert chunk["metadata"].get("status") == "completed", (
            f"Expected metadata status='completed' but got: {chunk['metadata']}"
        )

    def test_status_metadata_was_open_before_update(self, store_and_index):
        """Sanity check: status metadata starts as 'open' before the update."""
        store, index = store_and_index
        store.write_file(
            "todos.md",
            "---\ntype: todos\ndescription: Quests\n---\n\n"
            "## Find the Key\n**Subtype:** quest\n**Status:** open\n\n",
        )
        index.index_file(store, "todos.md")

        chunk = _get_chunk_direct(index, "todos.md::Find the Key")
        assert chunk is not None
        assert chunk["metadata"].get("status") == "open"

    def test_entity_type_metadata_preserved_after_update(self, store_and_index):
        """entity_type metadata must not be lost during a field update re-index."""
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n",
        )
        index.index_file(store, "people.md")

        store.update_entity("people.md", "Roger", {"Role": "Captain"})
        index.index_file(store, "people.md")

        chunk = _get_chunk_direct(index, "people.md::Roger")
        assert chunk is not None
        assert chunk["metadata"].get("entity_type") == "characters", (
            f"entity_type metadata lost after update: {chunk['metadata']}"
        )

    def test_entity_name_metadata_preserved_after_update(self, store_and_index):
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n",
        )
        index.index_file(store, "people.md")

        store.update_entity("people.md", "Roger", {"Status": "active"})
        index.index_file(store, "people.md")

        chunk = _get_chunk_direct(index, "people.md::Roger")
        assert chunk is not None
        assert chunk["metadata"].get("entity_name") == "Roger"


# ---------------------------------------------------------------------------
# Metadata filter correctness after update
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMetadataFilterAfterUpdate:
    def test_completed_quest_excluded_from_open_filter(self, store_and_index):
        """After marking a quest complete, a status=open metadata filter must
        no longer return it — the metadata in ChromaDB must be current."""
        store, index = store_and_index
        store.write_file(
            "todos.md",
            "---\ntype: todos\ndescription: Quests\n---\n\n"
            "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n"
            "## Fix Reactor\n**Subtype:** quest\n**Status:** open\n\n",
        )
        index.index_file(store, "todos.md")

        store.update_entity("todos.md", "Recover Loadmaster's Key", {"Status": "completed"})
        index.index_file(store, "todos.md")

        results = index.hybrid_search(
            filters={"entity_type": "todos", "status": "open"},
            top_k=10,
        )
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Recover Loadmaster's Key" not in names, (
            "Completed quest still returned by open-status filter after re-index"
        )
        assert "Fix Reactor" in names

    def test_completed_quest_returned_by_completed_filter(self, store_and_index):
        """After completion, the quest must be findable via status=completed filter."""
        store, index = store_and_index
        store.write_file(
            "todos.md",
            "---\ntype: todos\ndescription: Quests\n---\n\n"
            "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n",
        )
        index.index_file(store, "todos.md")

        store.update_entity("todos.md", "Recover Loadmaster's Key", {"Status": "completed"})
        index.index_file(store, "todos.md")

        results = index.hybrid_search(
            filters={"entity_type": "todos", "status": "completed"},
            top_k=10,
        )
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Recover Loadmaster's Key" in names

    def test_character_type_filter_unaffected_by_todo_update(self, store_and_index):
        """Updating a todo must not pollute character-type filter results."""
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n",
        )
        store.write_file(
            "todos.md",
            "---\ntype: todos\ndescription: Quests\n---\n\n"
            "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n",
        )
        index.index_file(store, "people.md")
        index.index_file(store, "todos.md")

        store.update_entity("todos.md", "Recover Loadmaster's Key", {"Status": "completed"})
        index.index_file(store, "todos.md")

        results = index.hybrid_search(
            filters={"entity_type": "characters"},
            top_k=10,
        )
        types = {r["metadata"]["entity_type"] for r in results}
        assert "todos" not in types


# ---------------------------------------------------------------------------
# Hash tracking correctness
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestHashTrackingAfterUpdate:
    def test_hash_updated_after_field_change(self, store_and_index):
        """After updating a field, the stored hash must differ from before —
        proving the chunk was actually re-embedded, not skipped."""
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n",
        )
        index.index_file(store, "people.md")

        hash_before = index.chunk_hashes.get("people.md::Roger")
        assert hash_before is not None

        store.update_entity("people.md", "Roger", {"Role": "Captain"})
        index.index_file(store, "people.md")

        hash_after = index.chunk_hashes.get("people.md::Roger")
        assert hash_after is not None
        assert hash_after != hash_before, (
            "Hash did not change after field update — chunk may not have been re-embedded"
        )

    def test_unchanged_entity_hash_stable_after_sibling_update(self, store_and_index):
        """Updating Roger must not invalidate Kira's hash (different chunk)."""
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n"
            "## Kira\n**Role:** Blacksmith\n**Status:** active\n\n",
        )
        index.index_file(store, "people.md")

        kira_hash_before = index.chunk_hashes.get("people.md::Kira")

        store.update_entity("people.md", "Roger", {"Role": "Captain"})
        index.index_file(store, "people.md")

        kira_hash_after = index.chunk_hashes.get("people.md::Kira")
        assert kira_hash_after == kira_hash_before, (
            "Kira's hash changed even though only Roger was updated"
        )

    def test_re_indexing_unchanged_file_returns_zero_updates(self, store_and_index):
        """index_file on an unmodified file must return 0 (no re-embedding)."""
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Captain\n**Status:** active\n\n",
        )
        index.index_file(store, "people.md")
        second_pass = index.index_file(store, "people.md")
        assert second_pass == 0

    def test_re_indexing_after_update_returns_nonzero(self, store_and_index):
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n",
        )
        index.index_file(store, "people.md")

        store.update_entity("people.md", "Roger", {"Role": "Captain"})
        second_pass = index.index_file(store, "people.md")
        assert second_pass > 0


# ---------------------------------------------------------------------------
# Semantic search relevance after update
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSemanticSearchAfterUpdate:
    def test_new_value_semantically_retrievable(self, store_and_index):
        """After updating Roger's role to Captain, a semantic query for
        'captain ship commander' must surface Roger."""
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n",
        )
        index.index_file(store, "people.md")

        store.update_entity("people.md", "Roger", {"Role": "Captain"})
        index.index_file(store, "people.md")

        results = index.search("captain ship commander", top_k=5)
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Roger" in names

    def test_outcome_field_semantically_retrievable(self, store_and_index):
        """After adding an Outcome field to a completed todo, that outcome text
        must be findable via semantic search."""
        store, index = store_and_index
        store.write_file(
            "todos.md",
            "---\ntype: todos\ndescription: Quests\n---\n\n"
            "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n",
        )
        index.index_file(store, "todos.md")

        store.update_entity(
            "todos.md",
            "Recover Loadmaster's Key",
            {"Status": "completed", "Outcome": "Found the key at Sorrell's fishing hab"},
        )
        index.index_file(store, "todos.md")

        results = index.search("Sorrell fishing hab key", top_k=5)
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Recover Loadmaster's Key" in names

    def test_history_note_semantically_retrievable(self, store_and_index):
        """After appending a history note to an entity, it must be findable
        via semantic search on the note's content."""
        store, index = store_and_index
        store.write_file(
            "people.md",
            "---\ntype: characters\ndescription: NPCs\n---\n\n"
            "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n\n",
        )
        index.index_file(store, "people.md")

        store.update_entity(
            "people.md",
            "Roger",
            updates={},
            append_history="Revealed to be working with the pirates.",
        )
        index.index_file(store, "people.md")

        results = index.search("pirates secret alliance", top_k=5)
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Roger" in names
