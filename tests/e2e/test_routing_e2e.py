"""E2E: intent routing — correct graph branch taken for each input type."""

import pytest


def files_modified_after(agent, message) -> bool:
    """Return True if any notebook .md file was touched during the chat call."""
    import time
    mtimes_before = {
        p: p.stat().st_mtime
        for p in agent.store.notebook_path.glob("*.md")
    }
    time.sleep(0.05)
    agent.chat(message)
    for p, before in mtimes_before.items():
        if p.stat().st_mtime != before:
            return True
    # Also check for newly created files
    after = set(agent.store.notebook_path.glob("*.md"))
    return len(after) > len(mtimes_before)


@pytest.mark.e2e
class TestRoutingRecord:
    def test_new_ore_creates_entry(self, agent):
        assert files_modified_after(agent, "Found a new ore called viridite near Facility Lambda")

    def test_new_npc_routes_to_record_not_update(self, agent):
        # A new person should always be record, never update (no existing entry to modify)
        agent.chat("I met an engineer named Holt near the surface")
        content = agent.store.read_file("people.md")
        assert "Holt" in content


@pytest.mark.e2e
class TestRoutingQuery:
    def test_query_does_not_modify_files(self, agent):
        assert not files_modified_after(agent, "Where is the fishing hab?")

    def test_question_about_known_entity_is_query(self, agent):
        assert not files_modified_after(agent, "What do I know about Facility Lambda?")


@pytest.mark.e2e
class TestRoutingUpdate:
    def test_mark_done_modifies_files(self, agent):
        assert files_modified_after(agent, "Mark 'Recover Loadmaster's Key' as done")

    def test_correction_modifies_files(self, agent):
        assert files_modified_after(agent, "Actually Roger is the captain not the loadmaster")


@pytest.mark.e2e
class TestRoutingBlockers:
    """Blocker and constraint statements must route to record, not chat."""

    def test_cant_access_because_requirement(self, agent):
        # "I can't X because Y" — blocked action is a new game fact
        assert files_modified_after(
            agent,
            "I can't access the Omicron climber control panel because it has a thermal warning",
        )

    def test_cant_fix_without_item(self, agent):
        # "I can't fix X without Y" — unmet requirement is a new fact
        assert files_modified_after(
            agent,
            "I can't fix the climber without a thermo-pump",
        )

    def test_need_plans_for_item(self, agent):
        # "I need the plans for X" — missing knowledge is a new fact
        assert files_modified_after(
            agent,
            "I need the plans for a thermo-pump",
        )

    def test_requires_dependency(self, agent):
        # "X requires Y" about a game object — dependency is a new fact
        assert files_modified_after(
            agent,
            "The elevator at Kappa requires a power cell to run",
        )


@pytest.mark.e2e
class TestRoutingChat:
    def test_greeting_does_not_modify_files(self, agent):
        assert not files_modified_after(agent, "Thanks, that's all for now")

    def test_meta_question_does_not_modify_files(self, agent):
        assert not files_modified_after(agent, "What can you help me with?")
