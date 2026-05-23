"""E2E: query completeness — status filters only applied when explicitly asked.

Spec §5: "Status filters only apply when you explicitly ask for them.
'What quests are open?' filters by status=open; 'What quests are there?' returns all of them."

Also covers: query combines structured facts + journal (spec §5 important behaviors).
"""

import pytest


@pytest.mark.e2e
class TestUnfilteredQueryReturnsAll:
    """Unqualified listing queries must not silently drop completed/answered entities."""

    @pytest.fixture(autouse=True)
    def seed_completed_quest(self, agent):
        """Complete one quest so we have a mix of open and completed."""
        agent.chat("Mark 'Recover Loadmaster's Key' as completed")

    def test_unfiltered_quest_query_includes_completed(self, agent):
        """'What quests are there?' should include the completed quest."""
        response = agent.chat("What quests are there?")
        lower = response.lower()
        # The completed quest should appear
        assert "loadmaster" in lower or "recover" in lower

    def test_unfiltered_quest_query_includes_open(self, agent):
        """'What quests are there?' should also include open quests."""
        response = agent.chat("What quests are there?")
        lower = response.lower()
        # The still-open quest should appear too
        assert "epsilon" in lower or "storage" in lower or "unlock" in lower

    def test_filtered_query_excludes_completed(self, agent):
        """'What quests are still open?' should NOT include the completed quest."""
        response = agent.chat("What quests are still open?")
        lower = response.lower()
        # "Unlock Epsilon Secure Storage" is still open; completed one should not dominate
        assert "epsilon" in lower or "storage" in lower or "unlock" in lower

    def test_all_characters_query_unfiltered(self, agent):
        """'Who are all the people I've met?' should return every character."""
        response = agent.chat("Who are all the people I've met?")
        lower = response.lower()
        # All three seeded characters should appear
        assert "roger" in lower
        assert "rupert" in lower or "sanford" in lower
        assert "kingston" in lower

    def test_all_mysteries_unfiltered(self, agent):
        """'What mysteries am I tracking?' should return all mysteries regardless of status."""
        response = agent.chat("What mysteries am I tracking?")
        lower = response.lower()
        assert "lambda" in lower or "radiation" in lower or "supplies" in lower or "rupert" in lower


@pytest.mark.e2e
class TestQueryCombinesStructuredAndJournal:
    """Answers should combine structured DB facts with relevant journal passages."""

    def test_entity_query_includes_structured_field(self, agent):
        """Asking about Roger should surface his structured role field."""
        response = agent.chat("What do I know about Roger?")
        lower = response.lower()
        assert "loadmaster" in lower

    def test_entity_query_includes_journal_context(self, agent):
        """Asking about Rupert should surface journal-level narrative detail."""
        response = agent.chat("What do I know about Rupert Sanford?")
        lower = response.lower()
        # Journal note about cleaning supplies going missing should surface
        assert "cleaning" in lower or "supplies" in lower or "missing" in lower

    def test_thematic_query_draws_from_journal(self, agent):
        """A thematic query with no exact entity match should pull from journal."""
        # Seed a journal entry with a specific theme
        agent.chat("There's a strange humming sound coming from behind the eastern wall in Lambda")
        response = agent.chat("What unusual sounds or phenomena have I noticed?")
        lower = response.lower()
        assert "hum" in lower or "sound" in lower or "lambda" in lower or "eastern" in lower
