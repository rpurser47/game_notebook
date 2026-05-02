"""Shared pytest fixtures."""

import pytest
from pathlib import Path
from src.storage.markdown import MarkdownStore


@pytest.fixture
def notebook_dir(tmp_path):
    """Fresh empty notebook directory."""
    return tmp_path / "notebook"


@pytest.fixture
def store(notebook_dir):
    """MarkdownStore backed by a fresh temp directory."""
    return MarkdownStore(notebook_dir)


@pytest.fixture
def seeded_store(store):
    """MarkdownStore pre-populated with a people.md and todos.md."""
    store.write_file(
        "people.md",
        "---\ntype: characters\ndescription: NPCs\n---\n\n"
        "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n"
        "**Related:** [[Loadmaster's Key]]\n\n- Lost the key.\n",
    )
    store.write_file(
        "todos.md",
        "---\ntype: todos\ndescription: Quests\n---\n\n"
        "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n"
        "- Find the key at the fishing hab.\n",
    )
    store.write_file(
        "journal.md",
        "---\ntype: observations\ndescription: Journal\n---\n\n"
        "# Journal\n\n## Session — initial\n- Started the notebook.\n",
    )
    return store
