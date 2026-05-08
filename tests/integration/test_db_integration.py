"""Integration tests: NotebookDB + MarkdownStore working together."""

import pytest
from src.storage.db import NotebookDB
from src.storage.markdown import MarkdownStore


@pytest.fixture
def db(tmp_path):
    return NotebookDB(tmp_path / "notebook")


@pytest.fixture
def store(tmp_path):
    return MarkdownStore(tmp_path / "notebook")


@pytest.fixture
def db_and_store(tmp_path):
    nb = tmp_path / "notebook"
    return NotebookDB(nb), MarkdownStore(nb)


def _seed_people(store):
    store.write_file(
        "people.md",
        "---\ntype: characters\ndescription: NPCs\n---\n\n"
        "## Roger\n**Role:** Loadmaster\n**Status:** unknown\n"
        "**Related:** [[Loadmaster's Key]]\n\n- Lost the key.\n",
    )


def _seed_places(store):
    store.write_file(
        "places.md",
        "---\ntype: locations\ndescription: Places\n---\n\n"
        "## Kappa Facility\n**Explored:** no\n**Status:** unknown\n\n"
        "## Facility Epsilon\n**Explored:** partial\n**Status:** active\n\n",
    )


# ---------------------------------------------------------------------------
# DB write → read round-trips
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestDBWriteAndQuery:
    def test_entity_written_and_read_back(self, db):
        eid = db.insert_entity("Kira", "characters", status="active")
        db.upsert_field(eid, "role", "blacksmith")
        entity = db.get_entity_by_name("Kira")
        assert entity.name == "Kira"
        assert entity.status == "active"
        assert entity.fields["role"] == "blacksmith"

    def test_entity_read_by_alias(self, db):
        eid = db.insert_entity("Samantha Corburn", "characters")
        db.insert_alias(eid, "Sam")
        entity = db.get_entity_by_name("Sam")
        assert entity.name == "Samantha Corburn"

    def test_get_entities_by_type(self, db):
        db.insert_entity("Kira", "characters", status="active")
        db.insert_entity("Roger", "characters", status="unknown")
        db.insert_entity("Millhaven", "locations")
        chars = db.get_entities_by_type("characters")
        names = [e.name for e in chars]
        assert "Kira" in names
        assert "Roger" in names
        assert "Millhaven" not in names

    def test_get_entities_filtered_by_status(self, db):
        db.insert_entity("Find the Key", "todos", status="open")
        db.insert_entity("Repair Reactor", "todos", status="completed")
        open_todos = db.get_entities_by_type("todos", status="open")
        names = [e.name for e in open_todos]
        assert "Find the Key" in names
        assert "Repair Reactor" not in names

    def test_get_entities_filtered_by_subtype(self, db):
        eid1 = db.insert_entity("Find the Key", "todos")
        db.upsert_field(eid1, "subtype", "quest")
        eid2 = db.insert_entity("Missing Supplies", "todos")
        db.upsert_field(eid2, "subtype", "mystery")
        quests = db.get_entities_by_type("todos", subtype="quest")
        names = [e.name for e in quests]
        assert "Find the Key" in names
        assert "Missing Supplies" not in names


# ---------------------------------------------------------------------------
# Provenance / facts log
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestProvenanceLog:
    def test_initial_insert_creates_fact(self, db):
        eid = db.insert_entity("Roger", "characters", status="unknown",
                               source="narrator", confidence="certain")
        rows = db._conn.execute(
            "SELECT * FROM facts WHERE entity_id = ? AND field = 'status'", (eid,)
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["source"] == "narrator"

    def test_field_update_records_old_and_new(self, db):
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster", source="narrator")
        db.upsert_field(eid, "role", "Captain", source="player_observed",
                        turn_text="Actually Roger is the captain.")
        rows = db._conn.execute(
            "SELECT old_value, new_value, source, turn_text FROM facts "
            "WHERE entity_id = ? AND field = 'role' ORDER BY id", (eid,)
        ).fetchall()
        assert rows[-1]["old_value"] == "Loadmaster"
        assert rows[-1]["new_value"] == "Captain"
        assert rows[-1]["source"] == "player_observed"
        assert rows[-1]["turn_text"] == "Actually Roger is the captain."

    def test_multiple_fields_each_get_fact_row(self, db):
        eid = db.insert_entity("Kira", "characters")
        db.upsert_field(eid, "role", "blacksmith")
        db.upsert_field(eid, "location", "Millhaven")
        count = db._conn.execute(
            "SELECT COUNT(*) FROM facts WHERE entity_id = ?", (eid,)
        ).fetchone()[0]
        assert count == 2


# ---------------------------------------------------------------------------
# Conflict detection in realistic scenarios
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestConflictDetectionRealistic:
    def test_exploration_update_not_blocked(self, db_and_store):
        """The bug scenario: explored=no in DB, player says explored=yes."""
        db, store = db_and_store
        _seed_places(store)
        eid = db.insert_entity("Kappa Facility", "locations")
        db.upsert_field(eid, "explored", "no", source="narrator")

        conflicts = db.detect_conflicts([
            {"entity": "Kappa Facility", "field": "explored",
             "old_value": "", "new_value": "yes"},
        ])
        assert conflicts == []

    def test_status_progression_not_blocked(self, db_and_store):
        """open → completed should not conflict even though values differ."""
        db, _ = db_and_store
        eid = db.insert_entity("Find the Key", "todos")
        db.upsert_field(eid, "status", "open", source="narrator")

        conflicts = db.detect_conflicts([
            {"entity": "Find the Key", "field": "status",
             "old_value": "", "new_value": "completed"},
        ])
        assert conflicts == []

    def test_explicit_wrong_prior_value_blocked(self, db_and_store):
        """Player says 'was captain, now pilot' but DB has Loadmaster."""
        db, _ = db_and_store
        eid = db.insert_entity("Roger", "characters")
        db.upsert_field(eid, "role", "Loadmaster", source="narrator")

        conflicts = db.detect_conflicts([
            {"entity": "Roger", "field": "role",
             "old_value": "captain", "new_value": "pilot"},
        ])
        assert len(conflicts) == 1
        assert conflicts[0]["db_value"] == "Loadmaster"

    def test_multiple_locations_only_flags_real_conflict(self, db_and_store):
        """Batch of updates for multiple locations — only the wrong one conflicts."""
        db, _ = db_and_store
        eid1 = db.insert_entity("Kappa Facility", "locations")
        db.upsert_field(eid1, "explored", "no")
        eid2 = db.insert_entity("Facility Epsilon", "locations")
        db.upsert_field(eid2, "status", "active")

        conflicts = db.detect_conflicts([
            # Routine — no old_value
            {"entity": "Kappa Facility", "field": "explored",
             "old_value": "", "new_value": "yes"},
            # Real conflict — wrong old_value stated
            {"entity": "Facility Epsilon", "field": "status",
             "old_value": "derelict", "new_value": "abandoned"},
        ])
        assert len(conflicts) == 1
        assert conflicts[0]["entity"] == "Facility Epsilon"


# ---------------------------------------------------------------------------
# Markdown rendered from DB state
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestMarkdownConsistency:
    def test_markdown_reflects_db_after_migration_style_write(self, db_and_store):
        """Write to both DB and markdown, verify markdown matches DB value."""
        db, store = db_and_store
        _seed_places(store)

        # Simulate what persist does: update DB then update markdown
        eid = db.insert_entity("Kappa Facility", "locations")
        db.upsert_field(eid, "explored", "no", source="narrator")
        db.upsert_field(eid, "explored", "yes", source="player_observed")
        store.update_entity("places.md", "Kappa Facility", {"Explored": "yes"})

        # DB and markdown should agree
        db_val = db.get_field("Kappa Facility", "explored")
        md_content = store.read_file("places.md")
        assert db_val == "yes"
        assert "**Explored:** yes" in md_content
