"""E2E: querying the notebook."""

import pytest


@pytest.mark.e2e
class TestQueryKnownNPC:
    def test_returns_rupert_details(self, agent):
        response = agent.chat("What do I know about Rupert Sanford?")
        lower = response.lower()
        assert "custodian" in lower or "cleaning" in lower or "supplies" in lower

    def test_returns_roger_details(self, agent):
        response = agent.chat("What do I know about Roger?")
        lower = response.lower()
        assert "key" in lower or "loadmaster" in lower


@pytest.mark.e2e
class TestQueryOpenQuests:
    def test_open_quests_returned(self, agent):
        response = agent.chat("What quests are still open?")
        lower = response.lower()
        # Both open quests from seed data should appear
        assert "epsilon" in lower or "key" in lower or "storage" in lower

    def test_does_not_hallucinate_completed_quests(self, agent):
        response = agent.chat("What quests are still open?")
        # No completed quests in seed data, so nothing should be marked done
        assert "completed" not in response.lower()


@pytest.mark.e2e
class TestQueryOpenMysteries:
    def test_mysteries_returned(self, agent):
        response = agent.chat("What mysteries am I tracking?")
        lower = response.lower()
        assert "lambda" in lower or "radiation" in lower or "supplies" in lower or "rupert" in lower


@pytest.mark.e2e
class TestQueryNumericCodes:
    """Regression for: asking about numeric codes returned nothing on first ask.

    The agent was failing to map access-code questions to entity_type='items',
    so the retrieve node fell through to a bare semantic search that missed them.
    """

    @pytest.fixture(autouse=True)
    def seed_codes(self, agent):
        """Add two known codes and one used code to the seeded notebook."""
        agent.chat("I found a crate code: 1234. Target lock not identified yet.")
        agent.chat("I found another crate code: 5678. Haven't used it.")
        agent.chat("I opened a locked box using code 9999.")

    def test_lists_all_numeric_codes_on_direct_request(self, agent):
        response = agent.chat("list all known numeric codes")
        assert "1234" in response
        assert "5678" in response
        assert "9999" in response

    def test_returns_codes_on_first_ask_without_rephrasing(self, agent):
        """The regression: first ask should return codes, not 'none recorded'."""
        response = agent.chat("what numeric codes do I have that I haven't used?")
        # At minimum the two unused codes should surface
        assert "1234" in response or "5678" in response

    def test_does_not_claim_no_codes_exist(self, agent):
        response = agent.chat("what numeric codes do I have?")
        lower = response.lower()
        assert "no codes" not in lower
        assert "haven't told me any" not in lower
        assert "none recorded" not in lower


@pytest.mark.e2e
class TestQueryDoesNotModifyFiles:
    def test_query_leaves_files_unchanged(self, agent):
        import time
        people_path = agent.store.notebook_path / "people.md"
        before_mtime = people_path.stat().st_mtime
        time.sleep(0.1)
        agent.chat("What do I know about Roger?")
        after_mtime = people_path.stat().st_mtime
        assert before_mtime == after_mtime
