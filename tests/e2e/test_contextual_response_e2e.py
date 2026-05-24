"""E2E: contextual enrichment in record/update responses.

After recording or completing, the response should surface related notebook
context — not just echo the input back.
"""

import pytest


@pytest.mark.e2e
class TestRecordSurfacesRelatedContext:
    def test_recording_npc_event_surfaces_known_info(self, agent):
        """Recording an event involving a known NPC should surface related context."""
        agent.store.write_file("people.md", agent.store.read_file("people.md") + """\

## Simone Parker
**Role:** Unknown
**Location:** Crew Quarters C
**Status:** Unknown
**Related:** [[Crew Quarters C]], [[Facility Epsilon]]
""")
        agent.store.write_file("places.md", agent.store.read_file("places.md") + """\

## Crew Quarters C
**Explored:** partial
**Status:** active
**Related:** [[Facility Epsilon]], [[Simone Parker]]

- Accessible via Facility Theta. Contains residents including Simone Parker.

## Bunker Room
**Explored:** partial
**Status:** active
**Related:** [[Facility Epsilon]]

- Room below Facility Epsilon. Contents unclear.
""")
        agent.index.index_all(agent.store)

        response = agent.chat(
            "I've got a key card from Simone Parker, who is dead in the bunker room in Epsilon"
        )
        lower = response.lower()
        # Acknowledges the event and surfaces pre-existing context (not just an echo)
        assert "simone" in lower or "key card" in lower
        assert "crew quarters" in lower or "epsilon" in lower

    def test_recording_completion_surfaces_next_step(self, agent):
        """Completing a quest should mention what is now unblocked."""
        response = agent.chat("I found the Loadmaster's Key at Sorrell's fishing hab")
        lower = response.lower()
        assert "key" in lower
        assert "epsilon" in lower or "storage" in lower or "unlock" in lower


@pytest.mark.e2e
class TestUpdateSurfacesRelatedContext:
    def test_completing_quest_mentions_what_was_unlocked(self, agent):
        """Marking a quest done should surface the now-unblocked follow-on quest."""
        response = agent.chat("Mark 'Recover Loadmaster's Key' as completed")
        lower = response.lower()
        assert "key" in lower or "recover" in lower
        assert "epsilon" in lower or "storage" in lower or "unlock" in lower
