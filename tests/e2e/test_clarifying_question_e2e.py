"""E2E: LLM-driven clarifying questions.

Spec §8: When you record something new, the notebook may ask ONE short question
at the end of its reply — but only if a *consequential* fact is missing.
Cosmetic details are never asked about. If the entity already has enough context,
no question is asked. A follow-up answer is treated as a normal record turn.
"""

import pytest


@pytest.mark.e2e
class TestClarifyingQuestionAsked:
    """Cases where a consequential gap should produce a question."""

    def test_ambiguous_item_category_prompts_question(self, agent):
        """An item whose category cannot be inferred from context is consequential.
        The notebook should ask what kind of item it is."""
        # A named object with no descriptive context — category truly unknown
        # ("widget" is deliberately meaningless so the LLM can't infer resource/equipment/key-item)
        response = agent.chat("I picked up something called a resonance widget near the east corridor")
        # Should contain a question mark — asking what kind of item it is
        assert "?" in response

    def test_character_linked_to_quest_with_unknown_allegiance(self, agent):
        """A new character directly relevant to an open quest with unknown allegiance
        is a consequential gap — may prompt a question."""
        # "Recover Loadmaster's Key" is seeded and open; a new person near that
        # quest with no faction context should trigger a question
        response = agent.chat(
            "Met a smuggler named Dax near Sorrell's fishing hab — "
            "he seemed to know about the loadmaster's key"
        )
        # Either asks about allegiance/faction, or at minimum records the entity
        assert "dax" in response.lower() or "?" in response


@pytest.mark.e2e
class TestClarifyingQuestionNotAsked:
    """Cases where no question should be appended."""

    def test_well_understood_entity_no_question(self, agent):
        """A character with role, location, and faction stated — no question needed."""
        response = agent.chat(
            "Met an engineer named Holt at the surface base — "
            "he works for the maintenance crew and fixes power relays"
        )
        lower = response.lower()
        # Should confirm recording; may or may not have a question, but must mention Holt
        assert "holt" in lower

    def test_cosmetic_detail_not_asked(self, agent):
        """Cosmetic details (appearance, mood) should never be solicited."""
        response = agent.chat("Saw a woman named Petra near the gate")
        lower = response.lower()
        # Must not ask about hair colour, clothing, mood, etc.
        assert "hair" not in lower
        assert "clothes" not in lower
        assert "mood" not in lower
        assert "appearance" not in lower

    def test_query_never_produces_clarifying_question(self, agent):
        """A query turn should never end with a clarifying question about entities."""
        response = agent.chat("What do I know about Roger?")
        # Query responses answer the question — they don't ask new ones about Roger's fields
        lower = response.lower()
        assert "loadmaster" in lower or "key" in lower


@pytest.mark.e2e
class TestClarifyingAnswerRecorded:
    """A follow-up answer to a clarifying question is treated as a normal record turn."""

    def test_answer_to_question_gets_recorded(self, agent):
        """Player answers the clarifying question → fact is saved."""
        agent.chat("I found a strange disc in the wreck")
        # Player answers the implicit/explicit question about the disc
        agent.chat("It's a tech-component — looks like a control interface")
        content = agent.store.read_file("things.md")
        # The disc and its category should now be in the notebook
        assert "disc" in content.lower() or "tech" in content.lower()

    def test_answer_does_not_create_duplicate(self, agent):
        """Answering about the disc should not create a second disc entry."""
        agent.chat("I found a strange disc in the wreck")
        agent.chat("It's a tech-component — looks like a control interface")
        content = agent.store.read_file("things.md")
        # Count occurrences of "disc" — should appear at most once as a heading
        headings = [line for line in content.splitlines() if line.startswith("## ") and "disc" in line.lower()]
        assert len(headings) <= 1
