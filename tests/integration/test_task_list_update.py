"""Integration tests: open task list stays correct across query → update → re-query.

Simulates the real player workflow:
  1. Query: what are my open tasks?
  2. Complete one of them.
  3. Query again — the completed task must be gone and the rest unchanged.

No LLM. NodeFactory.persist drives the writes; index.hybrid_search drives the reads.
"""

import pytest
from unittest.mock import MagicMock
from src.storage.db import NotebookDB
from src.storage.markdown import MarkdownStore
from src.storage.index import NotebookIndex
from src.agent.nodes import NodeFactory


@pytest.fixture
def stack(tmp_path):
    nb = tmp_path / "notebook"
    db = NotebookDB(nb)
    store = MarkdownStore(nb)
    index = NotebookIndex(nb, embedding_provider="local")
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="Noted.")
    factory = NodeFactory(llm, store, index, db)
    return factory, db, store, index


def _seed(store, db):
    store.write_file(
        "todos.md",
        "---\ntype: todos\ndescription: Quests, plans, and mysteries\n---\n\n"
        "## Recover Loadmaster's Key\n**Subtype:** quest\n**Status:** open\n\n"
        "- The key is probably at Sorrell's fishing hab.\n\n"
        "## Unlock Epsilon Secure Storage\n**Subtype:** quest\n**Status:** open\n\n"
        "- Requires the Loadmaster's Key.\n\n"
        "## Lambda Radiation Cause\n**Subtype:** mystery\n**Status:** open\n\n"
        "- Why is the Lambda swamp radioactive?\n\n"
        "## Fix Broken Airlock\n**Subtype:** plan\n**Status:** open\n\n"
        "- Airlock on level 2 needs repair.\n\n",
    )
    for name, subtype in [
        ("Recover Loadmaster's Key", "quest"),
        ("Unlock Epsilon Secure Storage", "quest"),
        ("Lambda Radiation Cause", "mystery"),
        ("Fix Broken Airlock", "plan"),
    ]:
        eid = db.insert_entity(name, "todos", status="open")
        db.upsert_field(eid, "subtype", subtype)


def _open_task_names(index):
    results = index.hybrid_search(
        filters={"entity_type": "todos", "status": "open"},
        top_k=20,
    )
    return {r["metadata"]["entity_name"] for r in results}


@pytest.mark.integration
class TestOpenTaskListAfterCompletion:
    def test_all_four_tasks_open_before_any_update(self, stack):
        factory, db, store, index = stack
        _seed(store, db)
        index.index_all(store)

        names = _open_task_names(index)
        assert "Recover Loadmaster's Key" in names
        assert "Unlock Epsilon Secure Storage" in names
        assert "Lambda Radiation Cause" in names
        assert "Fix Broken Airlock" in names

    def test_completed_task_removed_from_open_list(self, stack):
        factory, db, store, index = stack
        _seed(store, db)
        index.index_all(store)

        before = _open_task_names(index)
        assert "Recover Loadmaster's Key" in before

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

        after = _open_task_names(index)
        assert "Recover Loadmaster's Key" not in after

    def test_remaining_tasks_still_open_after_one_completion(self, stack):
        """The other three tasks must remain in the open list after one is completed."""
        factory, db, store, index = stack
        _seed(store, db)
        index.index_all(store)

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

        after = _open_task_names(index)
        assert "Unlock Epsilon Secure Storage" in after
        assert "Lambda Radiation Cause" in after
        assert "Fix Broken Airlock" in after

    def test_open_count_decreases_by_one_after_completion(self, stack):
        factory, db, store, index = stack
        _seed(store, db)
        index.index_all(store)

        before = _open_task_names(index)
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
        after = _open_task_names(index)

        assert len(after) == len(before) - 1

    def test_completing_two_tasks_removes_both_from_open_list(self, stack):
        factory, db, store, index = stack
        _seed(store, db)
        index.index_all(store)

        for name, turn in [
            ("Recover Loadmaster's Key", "I recovered the Loadmaster's Key"),
            ("Fix Broken Airlock", "I fixed the broken airlock on level 2"),
        ]:
            factory.persist({
                "intent": "update",
                "user_input": turn,
                "extracted_observations": [],
                "resolved_entities": [],
                "extracted_updates": [
                    {"entity": name, "field": "status",
                     "old_value": "open", "new_value": "completed"},
                ],
                "extracted_relationships": [],
            })

        after = _open_task_names(index)
        assert "Recover Loadmaster's Key" not in after
        assert "Fix Broken Airlock" not in after
        assert "Unlock Epsilon Secure Storage" in after
        assert "Lambda Radiation Cause" in after

    def test_db_open_count_matches_index_open_count(self, stack):
        """DB and index must agree on how many open tasks remain after a completion."""
        factory, db, store, index = stack
        _seed(store, db)
        index.index_all(store)

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

        db_open = db.get_entities_by_type("todos", status="open")
        index_open = _open_task_names(index)

        assert len(db_open) == len(index_open), (
            f"DB has {len(db_open)} open todos but index has {len(index_open)}: "
            f"DB={[e.name for e in db_open]}, index={index_open}"
        )

    def test_subtype_filter_still_works_after_completion(self, stack):
        """After completing the only open mystery, the mystery filter returns empty."""
        factory, db, store, index = stack
        _seed(store, db)
        index.index_all(store)

        factory.persist({
            "intent": "update",
            "user_input": "Solved the Lambda radiation mystery — damaged reactor leaking coolant",
            "extracted_observations": [],
            "resolved_entities": [],
            "extracted_updates": [
                {"entity": "Lambda Radiation Cause", "field": "status",
                 "old_value": "open", "new_value": "answered"},
            ],
            "extracted_relationships": [],
        })

        results = index.hybrid_search(
            filters={"entity_type": "todos", "status": "open", "subtype": "mystery"},
            top_k=10,
        )
        names = [r["metadata"]["entity_name"] for r in results]
        assert "Lambda Radiation Cause" not in names
