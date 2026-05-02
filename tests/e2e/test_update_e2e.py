"""E2E: corrections and status changes."""

import pytest


@pytest.mark.e2e
class TestUpdateQuestStatus:
    def test_quest_marked_completed_in_file(self, agent):
        agent.chat("I recovered the Loadmaster's Key")
        content = agent.store.read_file("todos.md")
        # Find the Recover Loadmaster's Key section and check its status
        idx = content.find("## Recover Loadmaster's Key")
        assert idx != -1
        section = content[idx: idx + 300]
        assert "completed" in section.lower()

    def test_response_acknowledges_completion(self, agent):
        response = agent.chat("I recovered the Loadmaster's Key")
        lower = response.lower()
        assert "key" in lower or "recover" in lower or "noted" in lower


@pytest.mark.e2e
class TestCorrectNPCRole:
    def test_role_updated_in_file(self, agent):
        agent.chat("Actually Roger is the captain, not the loadmaster")
        content = agent.store.read_file("people.md")
        idx = content.find("## Roger")
        assert idx != -1
        section = content[idx: idx + 200]
        assert "captain" in section.lower()

    def test_response_uses_noted_phrasing(self, agent):
        response = agent.chat("Actually Roger is the captain, not the loadmaster")
        assert "noted" in response.lower() or "updated" in response.lower() or "roger" in response.lower()

    def test_no_duplicate_roger_entry(self, agent):
        agent.chat("Actually Roger is the captain, not the loadmaster")
        content = agent.store.read_file("people.md")
        assert content.count("## Roger") == 1


@pytest.mark.e2e
class TestUpdateDoesNotCreateDuplicate:
    def test_existing_entity_not_duplicated(self, agent):
        agent.chat("Roger's role is loadmaster")
        content = agent.store.read_file("people.md")
        assert content.count("## Roger") == 1
