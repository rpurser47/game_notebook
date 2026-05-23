"""Unit tests for NotebookDB — in-memory SQLite, no LLM."""

import pytest
from src.storage.db import NotebookDB


@pytest.fixture
def db(tmp_path):
    return NotebookDB(tmp_path / "notebook")


# ---------------------------------------------------------------------------
# Entity CRUD
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestCreateEntity:
    def test_insert_returns_id(self, db):
        eid = db.insert_entity("Kira", "characters", status="active")
        assert isinstance(eid, int)
        assert eid > 0

    def test_get_by_name(self, db):
        db.insert_entity("Kira", "characters", status="active")
        entity = db.get_entity_by_name("Kira")
        assert entity is not None
        assert entity.name == "Kira"
        assert entity.type == "characters"
        assert entity.status == "active"

    def test_get_by_name_case_insensitive(self, db):
        db.insert_entity("Kira", "characters")
        assert db.get_entity_by_name("kira") is not None
        assert db.get_entity_by_name("KIRA") is not None

    def test_idempotent_on_same_name_and_type(self, db):
        id1 = db.insert_entity("Kira", "characters")
        id2 = db.insert_entity("Kira", "characters")
        assert id1 == id2
        count = db._conn.execute("SELECT COUNT(*) FROM entities WHERE name='Kira'").fetchone()[0]
        assert count == 1

    def test_missing_entity_returns_none(self, db):
        assert db.get_entity_by_name("Nobody") is None


@pytest.mark.unit
class TestUpdateEntityField:
    def test_field_written_and_readable(self, db):
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")
        val = db.get_field("Roger", "role")
        assert val == "Loadmaster"

    def test_field_overwritten_on_second_upsert(self, db):
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")
        db.upsert_field(eid, "role", "Captain")
        assert db.get_field("Roger", "role") == "Captain"

    def test_status_field_updates_entity_row(self, db):
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "status", "active")
        entity = db.get_entity_by_name("Roger")
        assert entity.status == "active"

    def test_fields_hydrated_on_get(self, db):
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")
        db.upsert_field(eid, "location", "Facility Epsilon")
        entity = db.get_entity_by_name("Roger")
        assert entity.fields["role"] == "Loadmaster"
        assert entity.fields["location"] == "Facility Epsilon"

    def test_missing_field_returns_none(self, db):
        db.insert_entity("Roger", "characters")
        assert db.get_field("Roger", "role") is None


@pytest.mark.unit
class TestFactsLog:
    def test_insert_writes_facts_row(self, db):
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster", source="player_observed", confidence="certain")
        rows = db._conn.execute(
            "SELECT * FROM facts WHERE entity_id = ? AND field = 'role'", (eid,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["new_value"] == "Loadmaster"
        assert rows[0]["source"] == "player_observed"
        assert rows[0]["confidence"] == "certain"

    def test_update_records_old_value(self, db):
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")
        db.upsert_field(eid, "role", "Captain")
        rows = db._conn.execute(
            "SELECT old_value, new_value FROM facts WHERE entity_id = ? AND field = 'role' ORDER BY id",
            (eid,)
        ).fetchall()
        assert rows[0]["old_value"] is None
        assert rows[0]["new_value"] == "Loadmaster"
        assert rows[1]["old_value"] == "Loadmaster"
        assert rows[1]["new_value"] == "Captain"

    def test_turn_text_stored(self, db):
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Captain", turn_text="Actually Roger is the captain.")
        row = db._conn.execute(
            "SELECT turn_text FROM facts WHERE entity_id = ? AND field = 'role'", (eid,)
        ).fetchone()
        assert row["turn_text"] == "Actually Roger is the captain."


@pytest.mark.unit
class TestRelationships:
    def test_insert_and_fetch_relationship(self, db):
        eid = db.insert_entity("Kira", "characters")
        db.insert_relationship(eid, "Millhaven", "is at")
        rels = db.get_relationships(eid)
        assert any(r["to_name"] == "Millhaven" and r["relation"] == "is at" for r in rels)

    def test_relationship_idempotent(self, db):
        eid = db.insert_entity("Kira", "characters")
        db.insert_relationship(eid, "Millhaven", "is at")
        db.insert_relationship(eid, "Millhaven", "is at")
        rels = db.get_relationships(eid)
        assert len(rels) == 1

    def test_related_hydrated_on_get(self, db):
        eid = db.insert_entity("Kira", "characters")
        db.insert_relationship(eid, "Millhaven", "related to")
        entity = db.get_entity_by_name("Kira")
        assert "Millhaven" in entity.related


@pytest.mark.unit
class TestAliasLookup:
    def test_entity_found_by_alias(self, db):
        eid = db.insert_entity("Samantha Corburn", "characters")
        db.insert_alias(eid, "Sam")
        entity = db.get_entity_by_name("Sam")
        assert entity is not None
        assert entity.name == "Samantha Corburn"

    def test_alias_idempotent(self, db):
        eid = db.insert_entity("Samantha Corburn", "characters")
        db.insert_alias(eid, "Sam")
        db.insert_alias(eid, "Sam")
        count = db._conn.execute(
            "SELECT COUNT(*) FROM aliases WHERE entity_id = ?", (eid,)
        ).fetchone()[0]
        assert count == 1

    def test_aliases_hydrated_on_get(self, db):
        eid = db.insert_entity("Samantha Corburn", "characters")
        db.insert_alias(eid, "Sam")
        entity = db.get_entity_by_name("Samantha Corburn")
        assert "Sam" in entity.aliases


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConflictDetection:
    def _seed_roger(self, db):
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")
        return eid

    def test_no_conflict_when_field_absent(self, db):
        db.insert_entity("Roger", "characters")
        conflicts = db.detect_conflicts([
            {"entity": "Roger", "field": "role", "old_value": "", "new_value": "Loadmaster"},
        ])
        assert conflicts == []

    def test_stable_field_contradicted_without_stated_prior_is_conflict(self, db):
        """Contradicting a stable field (role) without a stated prior still raises a conflict.
        Per spec §7: 'Roger is the loadmaster' when DB has 'captain' should ask for confirmation."""
        self._seed_roger(db)
        conflicts = db.detect_conflicts([
            {"entity": "Roger", "field": "role", "old_value": "", "new_value": "Captain"},
        ])
        assert len(conflicts) == 1
        assert conflicts[0]["db_value"] == "Loadmaster"
        assert conflicts[0]["proposed_value"] == "Captain"

    def test_no_conflict_when_new_value_matches_db(self, db):
        """Re-stating the same fact is not a conflict."""
        self._seed_roger(db)
        conflicts = db.detect_conflicts([
            {"entity": "Roger", "field": "role", "old_value": "", "new_value": "Loadmaster"},
        ])
        assert conflicts == []

    def test_conflict_when_explicit_old_value_is_wrong(self, db):
        """Player says 'was X, now Y' but DB has Z — that's a real conflict."""
        self._seed_roger(db)
        conflicts = db.detect_conflicts([
            {"entity": "Roger", "field": "role", "old_value": "captain", "new_value": "pilot"},
        ])
        assert len(conflicts) == 1
        assert conflicts[0]["entity"] == "Roger"
        assert conflicts[0]["db_value"] == "Loadmaster"
        assert conflicts[0]["proposed_value"] == "pilot"

    def test_multiple_updates_flags_both_conflicting_ones(self, db):
        """Both a stable-field contradiction (role) and an explicit wrong prior (location)
        should be flagged when each has a meaningful current value."""
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster")
        db.upsert_field(eid, "location", "Epsilon")
        conflicts = db.detect_conflicts([
            # Conflict — stable field contradicted (role is a stable field)
            {"entity": "Roger", "field": "role", "old_value": "", "new_value": "Captain"},
            # Conflict — explicit wrong old_value
            {"entity": "Roger", "field": "location", "old_value": "Delta", "new_value": "Surface"},
        ])
        assert len(conflicts) == 2
        fields_flagged = {c["field"] for c in conflicts}
        assert "role" in fields_flagged
        assert "location" in fields_flagged

    def test_unknown_entity_skipped(self, db):
        conflicts = db.detect_conflicts([
            {"entity": "Nobody", "field": "role", "old_value": "x", "new_value": "y"},
        ])
        assert conflicts == []

    def test_exploration_update_not_a_conflict(self, db):
        """Specifically reproduces the bug: explored=no in DB, player says explored=yes."""
        eid = db.insert_entity("Kappa Facility", "locations")
        db.upsert_field(eid, "explored", "no")
        conflicts = db.detect_conflicts([
            {"entity": "Kappa Facility", "field": "explored", "old_value": "", "new_value": "yes"},
        ])
        assert conflicts == []


@pytest.mark.unit
class TestGetKnownEntities:
    def test_returns_names_grouped_by_type(self, db):
        db.insert_entity("Kira", "characters")
        db.insert_entity("Millhaven", "locations")
        db.insert_entity("Find the Key", "todos")
        known = db.get_known_entities()
        assert "Kira" in known["characters"]
        assert "Millhaven" in known["locations"]
        assert "Find the Key" in known["todos"]

    def test_empty_db_returns_empty_dict(self, db):
        assert db.get_known_entities() == {}
