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
class TestQueryDoesNotModifyFiles:
    def test_query_leaves_files_unchanged(self, agent):
        import time
        people_path = agent.store.notebook_path / "people.md"
        before_mtime = people_path.stat().st_mtime
        time.sleep(0.1)
        agent.chat("What do I know about Roger?")
        after_mtime = people_path.stat().st_mtime
        assert before_mtime == after_mtime
