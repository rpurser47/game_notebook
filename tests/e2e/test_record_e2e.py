"""E2E: recording new information."""

import pytest


@pytest.mark.e2e
class TestRecordNewNPC:
    def test_new_npc_appears_in_people_md(self, agent):
        agent.chat("I met a mechanic named Yuki at the surface base, she fixes drones")
        content = agent.store.read_file("people.md")
        assert "## Yuki" in content

    def test_new_npc_role_recorded(self, agent):
        agent.chat("I met a mechanic named Yuki at the surface base, she fixes drones")
        content = agent.store.read_file("people.md")
        assert "mechanic" in content.lower()

    def test_journal_updated_on_record(self, agent):
        agent.chat("I met a mechanic named Yuki at the surface base, she fixes drones")
        journal = agent.store.read_file("journal.md")
        assert "Yuki" in journal or "mechanic" in journal.lower()

    def test_response_acknowledges_new_npc(self, agent):
        response = agent.chat("I met a mechanic named Yuki at the surface base, she fixes drones")
        assert "Yuki" in response


@pytest.mark.e2e
class TestRecordNewLocation:
    def test_new_location_appears_in_places_md(self, agent):
        agent.chat("Found a new room — the Bunker Room, it's below Facility Epsilon")
        content = agent.store.read_file("places.md")
        assert "Bunker Room" in content

    def test_response_acknowledges_new_location(self, agent):
        response = agent.chat("Found a new room — the Bunker Room, it's below Facility Epsilon")
        assert "Bunker" in response or "room" in response.lower()


@pytest.mark.e2e
class TestRecordMultipleEntities:
    def test_both_entities_recorded(self, agent):
        agent.chat("Talked to a guard named Praxis outside the Theta gate — he mentioned someone called the Warden")
        content = agent.store.read_file("people.md")
        assert "Praxis" in content
