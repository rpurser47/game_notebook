"""E2E: dependency chain statements.

Tests the hypothesis that compound statements expressing prerequisite chains
("I need to do X to get Y, and I need Y to turn on Z") are handled correctly.

A well-handled chain should produce:
- All named entities recorded (items, todos, locations)
- The prerequisite relationship captured (requires / related fields)
- A coherent response that acknowledges the chain, not just the last noun
"""

import pytest


def _section(content: str, heading: str, window: int = 400) -> str:
    """Return the text of a markdown section starting at ## heading."""
    idx = content.find(f"## {heading}")
    if idx == -1:
        return ""
    return content[idx: idx + window]


# ---------------------------------------------------------------------------
# Item + prerequisite chain: "I need X to get Y, and I need Y to use Z"
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestItemPrerequisiteChain:
    """'I need a thermo-pump to fix the climber, and I need the climber to reach the upper shaft.'

    Expected: thermo-pump (item), climber (item or location), upper shaft (location)
    all recorded; requires/related links captured.
    """

    INPUT = (
        "I need a thermo-pump to fix the climber, "
        "and I need the climber working to reach the upper shaft"
    )

    def test_thermo_pump_recorded(self, agent):
        agent.chat(self.INPUT)
        things = agent.store.read_file("things.md")
        assert "thermo-pump" in things.lower() or "thermo pump" in things.lower()

    def test_upper_shaft_recorded(self, agent):
        agent.chat(self.INPUT)
        places = agent.store.read_file("places.md")
        assert "upper shaft" in places.lower() or "shaft" in places.lower()

    def test_dependency_captured_somewhere(self, agent):
        """The prerequisite link (thermo-pump → climber → upper shaft) should appear
        in at least one of: a todo's Requires field, a Related link, or the journal."""
        agent.chat(self.INPUT)
        all_content = (
            agent.store.read_file("things.md")
            + agent.store.read_file("todos.md")
            + agent.store.read_file("journal.md")
        )
        lower = all_content.lower()
        # At minimum the two ends of the chain must co-exist in written content
        assert "thermo" in lower
        assert "shaft" in lower or "climber" in lower

    def test_response_acknowledges_full_chain(self, agent):
        """Response should not just echo the last noun — it should reflect the
        multi-step dependency so the player knows the chain was understood."""
        response = agent.chat(self.INPUT)
        lower = response.lower()
        # At least two of the three chain elements mentioned
        hits = sum([
            "thermo" in lower,
            "climber" in lower,
            "shaft" in lower,
        ])
        assert hits >= 2, f"Response only mentioned {hits}/3 chain elements: {response!r}"


# ---------------------------------------------------------------------------
# Todo requires chain: sequential quests with explicit prerequisite
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestTodoRequiresChain:
    """'I have to find the access card to open the security door, and I need
    the security door open to get to the generator room.'

    Expected:
    - "Find Access Card" (or similar) recorded as a todo
    - "Open Security Door" recorded as a todo with requires → access card todo
    - "Generator Room" recorded as a location
    - Chain linkage visible somewhere in the notebook
    """

    INPUT = (
        "I have to find the access card to open the security door, "
        "and I need the security door open to get to the generator room"
    )

    def test_access_card_recorded(self, agent):
        agent.chat(self.INPUT)
        things = agent.store.read_file("things.md")
        todos = agent.store.read_file("todos.md")
        assert "access card" in things.lower() or "access card" in todos.lower()

    def test_generator_room_recorded(self, agent):
        agent.chat(self.INPUT)
        places = agent.store.read_file("places.md")
        todos = agent.store.read_file("todos.md")
        assert "generator" in places.lower() or "generator" in todos.lower()

    def test_at_least_one_todo_created(self, agent):
        """A dependency chain involving tasks should produce at least one todo entry."""
        agent.chat(self.INPUT)
        todos = agent.store.read_file("todos.md")
        # Count new ## headings beyond the seeded ones
        seeded = {"Unlock Epsilon Secure Storage", "Recover Loadmaster's Key",
                  "Lambda Radiation Cause", "Rupert Sanford's Missing Supplies"}
        new_headings = [
            line for line in todos.splitlines()
            if line.startswith("## ") and line[3:] not in seeded
        ]
        assert len(new_headings) >= 1, f"No new todos created. todos.md:\n{todos}"

    def test_requires_or_related_links_chain(self, agent):
        """The prerequisite relationship between the two tasks should be captured
        as either a Requires field or a Related link in todos.md or things.md."""
        agent.chat(self.INPUT)
        todos = agent.store.read_file("todos.md")
        things = agent.store.read_file("things.md")
        combined = (todos + things).lower()
        # 'requires', 'related', or the two object names appearing in the same section
        has_explicit_link = "requires" in combined or "related" in combined
        has_both_objects = "access card" in combined and ("door" in combined or "generator" in combined)
        assert has_explicit_link or has_both_objects


# ---------------------------------------------------------------------------
# Three-hop chain: A → B → C
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestThreeHopChain:
    """'I need the fuel cell to power the lift, I need the lift to reach level 3,
    and I need level 3 to find the core sample.'

    This is the most complex variant — three entities, two dependency hops.
    Expected: all three entities recorded; chain linkage in at least one place.
    """

    INPUT = (
        "I need the fuel cell to power the lift, "
        "I need the lift to reach level 3, "
        "and I need level 3 to find the core sample"
    )

    def test_fuel_cell_recorded(self, agent):
        agent.chat(self.INPUT)
        things = agent.store.read_file("things.md")
        assert "fuel cell" in things.lower()

    def test_level_3_recorded(self, agent):
        agent.chat(self.INPUT)
        places = agent.store.read_file("places.md")
        todos = agent.store.read_file("todos.md")
        assert "level 3" in places.lower() or "level 3" in todos.lower()

    def test_core_sample_recorded(self, agent):
        agent.chat(self.INPUT)
        things = agent.store.read_file("things.md")
        todos = agent.store.read_file("todos.md")
        assert "core sample" in things.lower() or "core sample" in todos.lower()

    def test_all_three_chain_elements_in_notebook(self, agent):
        """All three chain elements must appear somewhere in the written notebook."""
        agent.chat(self.INPUT)
        all_content = "\n".join(
            agent.store.read_file(f)
            for f in ["things.md", "places.md", "todos.md", "journal.md"]
            if agent.store.read_file(f)
        ).lower()
        missing = [name for name in ["fuel cell", "lift", "core sample"]
                   if name not in all_content]
        assert not missing, f"Chain elements missing from notebook: {missing}"

    def test_response_references_at_least_two_chain_elements(self, agent):
        response = agent.chat(self.INPUT)
        lower = response.lower()
        hits = sum([
            "fuel cell" in lower,
            "lift" in lower,
            "level 3" in lower or "level three" in lower,
            "core sample" in lower,
        ])
        assert hits >= 2, f"Response only hit {hits}/4 chain elements: {response!r}"


# ---------------------------------------------------------------------------
# Chain with an already-known entity mid-chain
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestChainWithKnownEntity:
    """'I need to find the Loadmaster's Key to unlock Epsilon Secure Storage,
    and once that's open I can search for the thermo-pump.'

    Loadmaster's Key and Unlock Epsilon Secure Storage are seeded. The chain
    should update/link the known todos and add thermo-pump as a new item.
    """

    INPUT = (
        "I need to find the Loadmaster's Key to unlock Epsilon Secure Storage, "
        "and once that's open I can search for the thermo-pump"
    )

    def test_does_not_duplicate_known_key(self, agent):
        agent.chat(self.INPUT)
        things = agent.store.read_file("things.md")
        # Should not create a second copy of Loadmaster's Key
        assert things.count("Loadmaster's Key") <= 1

    def test_thermo_pump_recorded_as_new(self, agent):
        agent.chat(self.INPUT)
        things = agent.store.read_file("things.md")
        assert "thermo" in things.lower()

    def test_known_quest_not_unintentionally_completed(self, agent):
        """Mentioning the quest in a dependency context must not mark it completed."""
        agent.chat(self.INPUT)
        todos = agent.store.read_file("todos.md")
        section = _section(todos, "Recover Loadmaster's Key")
        # Status should still be open — the player hasn't found it yet
        assert "completed" not in section.lower(), (
            f"Quest incorrectly marked completed:\n{section}"
        )

    def test_response_connects_chain_to_thermo_pump(self, agent):
        """Response should acknowledge the new item and its place in the chain,
        not just say 'noted' about the known quest."""
        response = agent.chat(self.INPUT)
        lower = response.lower()
        assert "thermo" in lower or "pump" in lower, (
            f"Response didn't mention the new chain element: {response!r}"
        )
