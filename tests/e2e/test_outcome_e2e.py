"""E2E: Outcome/Resolution field written when a todo is completed.

When the user reports completing a quest or resolving a mystery, the agent
should add an Outcome (or Resolution) field to the todo summarising how/why
it was completed — not just flip Status to 'completed'.
"""

import re
import pytest


@pytest.mark.e2e
class TestOutcomeFieldOnCompletion:
    def test_completing_quest_adds_outcome_field(self, agent):
        """Recovering the key should add an Outcome field to the todo."""
        agent.chat("I recovered the Loadmaster's Key at Sorrell's fishing hab")

        content = agent.store.read_file("todos.md")
        idx = content.find("## Recover Loadmaster's Key")
        assert idx != -1
        section = content[idx: idx + 400]

        assert "**Outcome:**" in section or "**Resolution:**" in section, (
            f"Expected an Outcome or Resolution field in the completed todo, "
            f"but section reads:\n{section}"
        )

    def test_outcome_mentions_how_it_was_resolved(self, agent):
        """The Outcome value should reference the location or method of recovery,
        not just be a generic acknowledgement."""
        agent.chat("I recovered the Loadmaster's Key at Sorrell's fishing hab")

        content = agent.store.read_file("todos.md")
        idx = content.find("## Recover Loadmaster's Key")
        assert idx != -1
        section = content[idx: idx + 400]

        outcome_match = re.search(
            r"\*\*(?:Outcome|Resolution):\*\*\s*(.+)", section
        )
        assert outcome_match, "No Outcome/Resolution field found"
        outcome_value = outcome_match.group(1).strip().lower()

        # Should mention something meaningful — not empty, not just "completed"
        assert len(outcome_value) > 10, (
            f"Outcome is too short to be meaningful: {outcome_value!r}"
        )
        assert outcome_value not in ("completed", "done", "answered", "resolved"), (
            f"Outcome just echoes the status: {outcome_value!r}"
        )

    def test_completing_mystery_adds_outcome(self, agent):
        """Resolving a mystery should also get an Outcome field."""
        agent.chat(
            "I figured out why Lambda is radioactive — the damaged reactor "
            "is leaking coolant into the swamp water"
        )

        content = agent.store.read_file("todos.md")
        idx = content.find("## Lambda Radiation Cause")
        assert idx != -1
        section = content[idx: idx + 400]

        assert "**Outcome:**" in section or "**Resolution:**" in section, (
            f"Expected an Outcome or Resolution field after solving the mystery, "
            f"but section reads:\n{section}"
        )

    def test_explicit_mark_done_adds_outcome(self, agent):
        """Explicitly marking a quest done with 'mark as completed' should
        still produce an Outcome field, even without a rich description."""
        agent.chat("Mark 'Recover Loadmaster's Key' as completed")

        content = agent.store.read_file("todos.md")
        idx = content.find("## Recover Loadmaster's Key")
        assert idx != -1
        section = content[idx: idx + 400]

        assert "**Outcome:**" in section or "**Resolution:**" in section, (
            f"Expected Outcome field even for an explicit mark-done, "
            f"but section reads:\n{section}"
        )

    def test_open_todo_does_not_get_outcome(self, agent):
        """An open todo that is merely mentioned should not get an Outcome field."""
        agent.chat("I need to unlock Epsilon Secure Storage")

        content = agent.store.read_file("todos.md")
        idx = content.find("## Unlock Epsilon Secure Storage")
        assert idx != -1
        section = content[idx: idx + 400]

        # Status should still be open
        status_match = re.search(r"\*\*Status:\*\*\s*(.+)", section)
        assert status_match
        assert "open" in status_match.group(1).lower()

        # No Outcome on an open todo
        assert "**Outcome:**" not in section and "**Resolution:**" not in section, (
            "Open todo should not have an Outcome field"
        )
