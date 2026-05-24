"""E2E: dependency chain statements.

Tests that compound prerequisite statements ("I need X to do Y, and Y to reach Z")
record all chain entities, capture dependency links, and produce coherent responses.

Each scenario is ONE test that calls agent.chat() once and asserts all properties
of that result — rather than one LLM call per property.
"""

import pytest


def _section(content: str, heading: str, window: int = 400) -> str:
    """Return the text of a markdown section starting at ## heading."""
    idx = content.find(f"## {heading}")
    if idx == -1:
        return ""
    return content[idx: idx + window]


@pytest.mark.e2e
class TestItemPrerequisiteChain:
    """'I need a thermo-pump to fix the climber, and I need the climber to reach the upper shaft.'"""

    def test_chain_recorded_and_acknowledged(self, agent):
        response = agent.chat(
            "I need a thermo-pump to fix the climber, "
            "and I need the climber working to reach the upper shaft"
        )
        things = agent.store.read_file("things.md")
        places = agent.store.read_file("places.md")
        all_notebook = things + places + agent.store.read_file("todos.md") + agent.store.read_file("journal.md")

        # All chain elements recorded
        assert "thermo" in things.lower() or "thermo" in agent.store.read_file("todos.md").lower()
        assert "shaft" in places.lower() or "shaft" in agent.store.read_file("todos.md").lower()

        # Dependency link captured somewhere
        lower_notebook = all_notebook.lower()
        assert "thermo" in lower_notebook and ("shaft" in lower_notebook or "climber" in lower_notebook)

        # Response acknowledges at least two chain elements
        lower_resp = response.lower()
        hits = sum(["thermo" in lower_resp, "climber" in lower_resp, "shaft" in lower_resp])
        assert hits >= 2, f"Response only mentioned {hits}/3 chain elements: {response!r}"


@pytest.mark.e2e
class TestTodoRequiresChain:
    """'I have to find the access card to open the security door, and I need the door open to reach the generator room.'"""

    def test_chain_recorded_and_linked(self, agent):
        response = agent.chat(
            "I have to find the access card to open the security door, "
            "and I need the security door open to get to the generator room"
        )
        things = agent.store.read_file("things.md")
        todos = agent.store.read_file("todos.md")
        places = agent.store.read_file("places.md")
        combined = (things + todos + places).lower()

        # All chain entities recorded
        assert "access card" in combined
        assert "generator" in combined

        # At least one new todo created
        seeded = {"Unlock Epsilon Secure Storage", "Recover Loadmaster's Key",
                  "Lambda Radiation Cause", "Rupert Sanford's Missing Supplies"}
        new_todos = [l for l in todos.splitlines() if l.startswith("## ") and l[3:] not in seeded]
        assert len(new_todos) >= 1, f"No new todos created:\n{todos}"

        # Prerequisite relationship captured
        has_link = "requires" in combined or "related" in combined
        has_both = "access card" in combined and ("door" in combined or "generator" in combined)
        assert has_link or has_both


@pytest.mark.e2e
class TestThreeHopChain:
    """'I need the fuel cell to power the lift, the lift to reach level 3, and level 3 to find the core sample.'"""

    def test_all_chain_elements_recorded_and_response_coherent(self, agent):
        response = agent.chat(
            "I need the fuel cell to power the lift, "
            "I need the lift to reach level 3, "
            "and I need level 3 to find the core sample"
        )
        all_content = "\n".join(
            agent.store.read_file(f)
            for f in ["things.md", "places.md", "todos.md", "journal.md"]
        ).lower()

        # All three hop entities recorded
        missing = [e for e in ["fuel cell", "lift", "core sample"] if e not in all_content]
        assert not missing, f"Chain elements missing from notebook: {missing}"
        assert "level 3" in all_content or "level three" in all_content

        # Response references at least two elements
        lower = response.lower()
        hits = sum(["fuel cell" in lower, "lift" in lower,
                    "level 3" in lower or "level three" in lower, "core sample" in lower])
        assert hits >= 2, f"Response only hit {hits}/4 chain elements: {response!r}"


@pytest.mark.e2e
class TestChainWithKnownEntity:
    """Chain involving seeded entities: Loadmaster's Key / Unlock Epsilon Secure Storage."""

    def test_known_entity_not_duplicated_new_entity_recorded(self, agent):
        response = agent.chat(
            "I need to find the Loadmaster's Key to unlock Epsilon Secure Storage, "
            "and once that's open I can search for the thermo-pump"
        )
        things = agent.store.read_file("things.md")
        todos = agent.store.read_file("todos.md")

        # Known entity not duplicated
        assert things.count("Loadmaster's Key") <= 1

        # New entity recorded
        assert "thermo" in things.lower()

        # Quest not unintentionally completed
        section = _section(todos, "Recover Loadmaster's Key")
        assert "completed" not in section.lower(), f"Quest incorrectly completed:\n{section}"

        # Response acknowledges the new chain element
        assert "thermo" in response.lower() or "pump" in response.lower(), (
            f"Response didn't mention the new chain element: {response!r}"
        )
