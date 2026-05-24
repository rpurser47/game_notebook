"""E2E: relationship recording — narrated links between entities are stored
and retrievable in later queries.

Each test records a relationship and then queries for it in the same turn sequence,
avoiding a separate agent fixture per direction.
"""

import pytest


@pytest.mark.e2e
class TestRelationshipRecordedAndRetrievable:
    """Record a relationship, then verify it surfaces in a query."""

    def test_faction_relationship_stored_and_queryable(self, agent):
        """'Vex works for the Syndicate' → stored in DB and surfaces on query."""
        agent.chat("Met a guard named Vex at the checkpoint — she works for the Syndicate")

        entity = agent.db.get_entity_by_name("Vex")
        assert entity is not None
        related_names = [r.lower() for r in (entity.related or [])]
        fields_text = " ".join(str(v) for v in entity.fields.values()).lower()
        assert "syndicate" in related_names or "syndicate" in fields_text

        response = agent.chat("What do I know about Vex?")
        lower = response.lower()
        assert "vex" in lower
        assert "syndicate" in lower or "checkpoint" in lower

    def test_location_relationship_stored_and_queryable(self, agent):
        """'Maren works in the lower library' → location stored and retrievable."""
        agent.chat(
            "Met an archivist named Maren in the lower library — "
            "she maintains the historical records"
        )

        entity = agent.db.get_entity_by_name("Maren")
        assert entity is not None
        fields_text = " ".join(str(v) for v in entity.fields.values()).lower()
        related_names = [r.lower() for r in (entity.related or [])]
        assert "library" in fields_text or any("library" in r for r in related_names)

        response = agent.chat("Where is Maren?")
        lower = response.lower()
        assert "library" in lower or "archive" in lower or "lower" in lower

    def test_multi_entity_scene_links_queryable(self, agent):
        """A scene with multiple known entities creates cross-entity links."""
        agent.chat(
            "Ran into Kingston and Rupert arguing in the supply room — "
            "Kingston was denying any knowledge of the missing cleaning supplies"
        )
        response = agent.chat("What's the deal with Rupert's missing supplies?")
        lower = response.lower()
        assert "kingston" in lower or "supply" in lower or "cleaning" in lower
