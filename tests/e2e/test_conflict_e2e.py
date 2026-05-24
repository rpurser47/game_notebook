"""E2E: conflict detection — agent asks for confirmation instead of silently overwriting.

Spec §7: A conflict is raised when the player contradicts a stable fact (role, category)
currently in the notebook. The write is held and the player is asked to confirm.
"""

import re
import pytest


@pytest.mark.e2e
class TestConflictResponseBehavior:
    """The agent must surface the conflict and ask for confirmation, not silently overwrite."""

    @pytest.fixture(autouse=True)
    def set_roger_captain(self, agent):
        """Seed Roger's role as captain directly in DB and markdown."""
        entity = agent.db.get_entity_by_name("Roger")
        if entity:
            agent.db.upsert_field(entity.id, "role", "captain")
        content = agent.store.read_file("people.md")
        content = re.sub(r"\*\*Role:\*\* Loadmaster", "**Role:** captain", content)
        agent.store.write_file("people.md", content)
        agent.index.index_file(agent.store, "people.md")

    def test_conflict_detected_response_asks_and_does_not_overwrite(self, agent):
        """Single call: conflict flagged, response asks for confirmation, file unchanged."""
        response = agent.chat("Roger is the loadmaster")
        lower = response.lower()

        # Response mentions the current value
        assert "captain" in lower or "loadmaster" in lower

        # Response asks for confirmation
        assert any(w in lower for w in ("confirm", "correct", "mean", "which", "change", "?")), (
            f"No confirmation request in response: {response!r}"
        )

        # File not overwritten — captain must still be present
        content = agent.store.read_file("people.md")
        assert "captain" in content.lower(), "Conflict silently overwrote the file"

    def test_no_conflict_on_same_value(self, agent):
        """Re-stating the current value (captain) should not trigger a conflict warning."""
        response = agent.chat("Roger is the captain")
        lower = response.lower()
        assert "conflict" not in lower and "contradict" not in lower

    def test_no_conflict_on_empty_field(self, agent):
        """Filling in an empty field should never be treated as a conflict."""
        response = agent.chat("Kingston is the security chief")
        lower = response.lower()
        assert "conflict" not in lower and "contradict" not in lower


@pytest.mark.e2e
class TestConflictConfirmationFlow:
    """An explicit correction (with stated prior) resolves the conflict."""

    def test_explicit_correction_after_conflict_updates_file(self, agent):
        """Stating the correct prior value bypasses the conflict guard and writes."""
        agent.chat("Roger is the captain")                             # stable-field conflict
        agent.chat("Actually Roger is the captain, not the loadmaster")  # explicit prior → writes
        content = agent.store.read_file("people.md")
        assert "captain" in content.lower()
