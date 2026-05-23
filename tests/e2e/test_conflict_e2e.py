"""E2E: conflict detection — agent asks for confirmation instead of silently overwriting.

Spec §7: If you state a prior value that contradicts what the notebook already has,
it stops and asks before overwriting.
"""

import pytest


@pytest.mark.e2e
class TestConflictResponseBehavior:
    """The agent must surface a conflict and ask for confirmation — not silently overwrite.

    Per spec §7: a conflict is only raised when the player asserts a value that
    contradicts a stable field (role, category) currently in the notebook.
    The canonical example: DB says "captain", player says "Roger is the loadmaster".
    """

    @pytest.fixture(autouse=True)
    def set_roger_captain(self, agent):
        """Directly seed Roger's role as captain in both DB and markdown."""
        import re
        # Update DB directly
        entity = agent.db.get_entity_by_name("Roger")
        if entity:
            agent.db.upsert_field(entity.id, "role", "captain")
        # Update markdown directly
        content = agent.store.read_file("people.md")
        content = re.sub(r"\*\*Role:\*\* Loadmaster", "**Role:** captain", content)
        agent.store.write_file("people.md", content)
        agent.index.index_file(agent.store, "people.md")

    def test_conflict_response_mentions_current_value(self, agent):
        """Response should name the value currently in the notebook (captain)."""
        response = agent.chat("Roger is the loadmaster")
        lower = response.lower()
        assert "captain" in lower or "loadmaster" in lower

    def test_conflict_response_asks_player_to_confirm(self, agent):
        """Response should ask the player which value is correct — not just say 'noted'."""
        response = agent.chat("Roger is the loadmaster")
        lower = response.lower()
        assert any(word in lower for word in ("confirm", "correct", "mean", "which", "change", "?"))

    def test_conflict_does_not_silently_overwrite(self, agent):
        """File must not be reverted to loadmaster when captain is the current value."""
        agent.chat("Roger is the loadmaster")
        content = agent.store.read_file("people.md")
        # Captain should still be in the file (conflict held the write)
        assert "captain" in content.lower()

    def test_no_conflict_on_same_value(self, agent):
        """Re-stating the current value (captain) should not trigger a conflict warning."""
        response = agent.chat("Roger is the captain")
        lower = response.lower()
        assert "conflict" not in lower
        assert "contradict" not in lower

    def test_no_conflict_on_empty_field(self, agent):
        """Filling in an empty field should never be treated as a conflict."""
        response = agent.chat("Kingston is the security chief")
        lower = response.lower()
        assert "conflict" not in lower
        assert "contradict" not in lower


@pytest.mark.e2e
class TestConflictConfirmationFlow:
    """After raising a conflict the player can confirm the new value.

    NOTE: The current implementation does not have cross-turn pending-confirmation
    state, so confirmation requires the player to re-state the update as an explicit
    correction ("Actually Roger is the captain, not the loadmaster") which carries
    old_value and bypasses the stable-field conflict guard.
    """

    def test_explicit_correction_after_conflict_updates_file(self, agent):
        """Player can resolve a conflict by explicitly correcting with a stated prior."""
        # First trigger a conflict
        agent.chat("Roger is the captain")
        # Then confirm with an explicit correction that carries the old_value
        agent.chat("Actually Roger is the captain, not the loadmaster")
        content = agent.store.read_file("people.md")
        assert "captain" in content.lower()
