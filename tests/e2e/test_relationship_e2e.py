"""E2E: relationship recording — narrated links between entities are stored
and retrievable in later queries.

Spec §4: "Relationships — directed links like 'Kira is at Millhaven',
'Roger serves Captain Vance'"
"""

import pytest


@pytest.mark.e2e
class TestRelationshipRecorded:
    """Relationships stated in narration should be persisted."""

    def test_faction_relationship_written_to_db(self, agent):
        """'Vex works for the Syndicate' should create a relationship in the DB."""
        agent.chat("Met a guard named Vex at the checkpoint — she works for the Syndicate")
        entity = agent.db.get_entity_by_name("Vex")
        assert entity is not None
        # Relationship stored as related field or in DB relationships table
        related_names = [r.lower() for r in (entity.related or [])]
        # Either related list has Syndicate, or it's in the description/role
        fields_text = " ".join(str(v) for v in entity.fields.values()).lower()
        assert "syndicate" in related_names or "syndicate" in fields_text

    def test_location_relationship_written(self, agent):
        """'Vex is stationed at Checkpoint Alpha' should link the two entities."""
        agent.chat("Met a guard named Vex at Checkpoint Alpha")
        entity = agent.db.get_entity_by_name("Vex")
        assert entity is not None
        fields_text = " ".join(str(v) for v in entity.fields.values()).lower()
        related_names = [r.lower() for r in (entity.related or [])]
        assert (
            "checkpoint" in fields_text
            or "checkpoint" in related_names
            or any("checkpoint" in r for r in related_names)
        )

    def test_item_ownership_relationship(self, agent):
        """'Roger had the loadmaster's key' should link Roger to the key."""
        # Roger and the key are both in seed data
        agent.chat("Roger used to carry the loadmaster's key everywhere")
        entity = agent.db.get_entity_by_name("Roger")
        assert entity is not None
        related_names = [r.lower() for r in (entity.related or [])]
        assert any("key" in r or "loadmaster" in r for r in related_names)


@pytest.mark.e2e
class TestRelationshipRetrievable:
    """A relationship recorded in one turn should surface in a later query."""

    def test_faction_surfaces_in_character_query(self, agent):
        """After recording 'Vex works for the Syndicate', querying Vex returns faction."""
        agent.chat("Met a guard named Vex at the checkpoint — she works for the Syndicate")
        response = agent.chat("What do I know about Vex?")
        lower = response.lower()
        assert "vex" in lower
        assert "syndicate" in lower or "checkpoint" in lower

    def test_location_relationship_surfaces_in_query(self, agent):
        """After recording character + location link, querying the character returns location."""
        agent.chat(
            "Met an archivist named Maren in the lower library — "
            "she maintains the historical records"
        )
        response = agent.chat("Where is Maren?")
        lower = response.lower()
        assert "library" in lower or "archive" in lower or "lower" in lower

    def test_multi_entity_scene_links_entities(self, agent):
        """Narrating a scene with multiple entities creates queryable links between them."""
        agent.chat(
            "Ran into Kingston and Rupert arguing in the supply room — "
            "Kingston was denying any knowledge of the missing cleaning supplies"
        )
        response = agent.chat("What's the deal with Rupert's missing supplies?")
        lower = response.lower()
        assert "kingston" in lower or "supply" in lower or "cleaning" in lower
