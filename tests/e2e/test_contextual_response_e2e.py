"""E2E: contextual enrichment in record/update responses.

After recording an observation or completing a todo, the response should
surface relevant related information already in the notebook — not just
acknowledge what was recorded.
"""

import pytest


@pytest.mark.e2e
class TestRecordSurfacesRelatedContext:
    def test_recording_npc_event_includes_known_info_about_that_npc(self, agent):
        """Recording Simone's death should surface what we already know about her
        (e.g. Crew Quarters C) rather than just echoing the input back."""
        # Seed Simone and Crew Quarters C into the notebook first
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

        # Should acknowledge the event
        assert "simone" in lower or "key card" in lower

        # Should surface what we know about Simone — not just echo the input
        assert "crew quarters" in lower or "epsilon" in lower

    def test_recording_completion_surfaces_next_step(self, agent):
        """Recording that the Loadmaster's Key was recovered should mention
        Unlock Epsilon Secure Storage as a now-unblocked next step."""
        response = agent.chat("I found the Loadmaster's Key at Sorrell's fishing hab")
        lower = response.lower()

        # Should confirm what was recorded
        assert "key" in lower

        # Should surface the next step that is now unblocked
        assert "epsilon" in lower or "storage" in lower or "unlock" in lower

    def test_response_is_not_just_an_echo(self, agent):
        """Response should add value beyond restating the user's input."""
        response = agent.chat(
            "I've got a key card from Simone Parker, who is dead in the bunker room in Epsilon"
        )
        # A pure echo would be ~the same length as the input and contain nothing extra.
        # A contextual response will be longer and mention things the user didn't say.
        assert len(response) > 80


@pytest.mark.e2e
class TestUpdateSurfacesRelatedContext:
    def test_completing_quest_mentions_what_was_unlocked(self, agent):
        """Marking 'Recover Loadmaster's Key' as done should surface
        'Unlock Epsilon Secure Storage' as now available."""
        response = agent.chat("Mark 'Recover Loadmaster's Key' as completed")
        lower = response.lower()

        assert "key" in lower or "recover" in lower
        assert "epsilon" in lower or "storage" in lower or "unlock" in lower

    def test_update_response_not_just_noted(self, agent):
        """A bare 'Noted.' with no context is not good enough for a completion event."""
        response = agent.chat("I recovered the Loadmaster's Key")
        # Should be more than just "Noted." or "Got it."
        assert len(response) > 40
        assert response.strip().lower() not in ("noted.", "got it.", "noted")
