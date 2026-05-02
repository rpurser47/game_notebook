"""E2E: status propagation to related entities when a quest is completed.

Theory: when the user says a quest is done, the agent updates the todo status
but may NOT update the status of related entities (items, characters, places)
mentioned in the todo's Related field. These tests verify that it does.
"""

import pytest


@pytest.mark.e2e
class TestQuestCompletionPropagatesStatus:
    def test_completing_key_recovery_quest_updates_key_status(self, agent):
        """When 'Recover Loadmaster's Key' is marked done, the Loadmaster's Key
        item in things.md should also have its status updated to reflect it was
        found — not remain 'lost'."""
        # Seed things.md with the Loadmaster's Key at 'lost' status
        agent.store.write_file("things.md", """\
---
type: items
description: Key items and equipment
---

## Loadmaster's Key
**Category:** key-item
**Status:** lost (not recovered)
**Location:** Probable: [[Theta Shack]] (Sorrell's fishing hab)
**Related:** [[Roger]], [[Sorrell]], [[Epsilon Secure Storage]]

- Opens Epsilon's Secure Storage.
- Roger (Loadmaster) lost it — told Jack about it.
- Probable location: Sorrell's fishing hab near Theta. Not yet recovered.
""")
        agent.index.index_all(agent.store)

        agent.chat("I recovered the Loadmaster's Key at Sorrell's fishing hab")

        things_content = agent.store.read_file("things.md")
        idx = things_content.find("## Loadmaster's Key")
        assert idx != -1, "Loadmaster's Key section not found in things.md"
        section = things_content[idx: idx + 300]

        # The Status field specifically should no longer say 'lost'
        import re
        status_match = re.search(r"\*\*Status:\*\*\s*(.+)", section)
        assert status_match is not None, f"No Status field found in section:\n{section}"
        status_value = status_match.group(1).strip().lower()
        assert "lost" not in status_value, (
            "Expected Loadmaster's Key Status to be updated away from 'lost' "
            f"after recovery, but Status is: {status_value!r}"
        )

    def test_completing_key_recovery_quest_updates_todo_AND_key(self, agent):
        """Both the todo AND the related item should be updated — not just the todo."""
        agent.store.write_file("things.md", """\
---
type: items
description: Key items and equipment
---

## Loadmaster's Key
**Category:** key-item
**Status:** lost (not recovered)
**Location:** Probable: [[Theta Shack]] (Sorrell's fishing hab)
**Related:** [[Roger]], [[Sorrell]], [[Epsilon Secure Storage]]

- Opens Epsilon's Secure Storage.
""")
        agent.index.index_all(agent.store)

        agent.chat("I recovered the Loadmaster's Key at Sorrell's fishing hab")

        todos_content = agent.store.read_file("todos.md")
        todo_idx = todos_content.find("## Recover Loadmaster's Key")
        assert todo_idx != -1
        todo_section = todos_content[todo_idx: todo_idx + 300]
        assert "completed" in todo_section.lower(), (
            "Todo was not marked completed"
        )

        things_content = agent.store.read_file("things.md")
        key_idx = things_content.find("## Loadmaster's Key")
        assert key_idx != -1
        key_section = things_content[key_idx: key_idx + 300]
        assert "lost" not in key_section.lower(), (
            "Loadmaster's Key status was not updated away from 'lost' in things.md"
        )

    def test_completing_quest_does_not_just_update_todo(self, agent):
        """Regression: the agent used to only touch todos.md. This test documents
        the gap — the related item status must also change."""
        agent.store.write_file("things.md", """\
---
type: items
description: Key items and equipment
---

## Loadmaster's Key
**Category:** key-item
**Status:** lost (not recovered)
**Location:** unknown
**Related:** [[Roger]]

- Opens Epsilon's Secure Storage.
""")
        agent.index.index_all(agent.store)

        agent.chat("Found the Loadmaster's Key — it was at Sorrell's fishing hab")

        things_content = agent.store.read_file("things.md")
        key_idx = things_content.find("## Loadmaster's Key")
        assert key_idx != -1
        key_section = things_content[key_idx: key_idx + 300]

        assert "lost" not in key_section.lower(), (
            "Agent only updated the todo but left the item status as 'lost'"
        )
