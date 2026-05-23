"""SQLite canonical store for structured world state."""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    status      TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(name, type)
);

CREATE TABLE IF NOT EXISTS aliases (
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias       TEXT NOT NULL,
    PRIMARY KEY (entity_id, alias)
);

CREATE TABLE IF NOT EXISTS entity_fields (
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    field       TEXT NOT NULL,
    value       TEXT NOT NULL,
    PRIMARY KEY (entity_id, field)
);

CREATE TABLE IF NOT EXISTS relationships (
    from_id     INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    to_name     TEXT NOT NULL,
    relation    TEXT NOT NULL,
    asserted_at TEXT NOT NULL,
    PRIMARY KEY (from_id, to_name, relation)
);

CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    field       TEXT NOT NULL,
    old_value   TEXT,
    new_value   TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'player_observed',
    confidence  TEXT NOT NULL DEFAULT 'certain',
    asserted_at TEXT NOT NULL,
    turn_text   TEXT
);

CREATE TABLE IF NOT EXISTS entity_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    note        TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reflections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,
    note        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_status ON entities(status);
CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases(alias);
CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_id);
CREATE INDEX IF NOT EXISTS idx_history_entity ON entity_history(entity_id);
"""


@dataclass
class EntityRow:
    id: int
    name: str
    type: str
    status: str | None
    fields: dict = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)


class NotebookDB:
    """SQLite canonical store."""

    def __init__(self, notebook_path: str | Path, db_filename: str = "notebook.db"):
        self.notebook_path = Path(notebook_path)
        db_dir = self.notebook_path / ".db"
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_dir / db_filename
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._apply_schema()

    def _apply_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _now(self) -> str:
        return datetime.now().isoformat()

    # -------------------------------------------------------------------------
    # Entity CRUD
    # -------------------------------------------------------------------------

    def insert_entity(
        self,
        name: str,
        type: str,
        status: str | None = None,
        source: str = "player_observed",
        confidence: str = "certain",
        turn_text: str | None = None,
    ) -> int:
        """Insert a new entity. Returns the entity id. Idempotent on (name, type)."""
        now = self._now()
        cur = self._conn.execute(
            """
            INSERT INTO entities (name, type, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name, type) DO UPDATE SET updated_at=excluded.updated_at
            RETURNING id
            """,
            (name, type, status, now, now),
        )
        row = cur.fetchone()
        entity_id = row["id"]

        if status:
            self._upsert_field_internal(entity_id, "status", status, source, confidence, turn_text, now)

        self._conn.commit()
        return entity_id

    def get_entity_by_name(self, name: str) -> EntityRow | None:
        """Fetch an entity by exact name (case-insensitive). Returns first match."""
        row = self._conn.execute(
            "SELECT * FROM entities WHERE lower(name) = lower(?)", (name,)
        ).fetchone()
        if not row:
            # Try alias lookup
            alias_row = self._conn.execute(
                """
                SELECT e.* FROM entities e
                JOIN aliases a ON a.entity_id = e.id
                WHERE lower(a.alias) = lower(?)
                """,
                (name,),
            ).fetchone()
            if not alias_row:
                return None
            row = alias_row

        return self._hydrate(row)

    def get_entities_by_type(
        self,
        entity_type: str,
        status: str | None = None,
        subtype: str | None = None,
    ) -> list[EntityRow]:
        """Fetch all entities of a given type, with optional status/subtype filter."""
        params: list = [entity_type]
        where = "WHERE e.type = ?"

        if status:
            where += " AND lower(e.status) = lower(?)"
            params.append(status)

        rows = self._conn.execute(
            f"SELECT e.* FROM entities e {where} ORDER BY e.name",
            params,
        ).fetchall()

        results = []
        for row in rows:
            entity = self._hydrate(row)
            if subtype:
                if entity.fields.get("subtype", "").lower() != subtype.lower():
                    continue
            results.append(entity)

        return results

    def _hydrate(self, row: sqlite3.Row) -> EntityRow:
        """Hydrate an entity row with its fields, aliases, and relationships."""
        entity_id = row["id"]

        fields_rows = self._conn.execute(
            "SELECT field, value FROM entity_fields WHERE entity_id = ?", (entity_id,)
        ).fetchall()
        fields = {r["field"]: r["value"] for r in fields_rows}

        alias_rows = self._conn.execute(
            "SELECT alias FROM aliases WHERE entity_id = ?", (entity_id,)
        ).fetchall()
        aliases = [r["alias"] for r in alias_rows]

        rel_rows = self._conn.execute(
            "SELECT to_name FROM relationships WHERE from_id = ?", (entity_id,)
        ).fetchall()
        related = [r["to_name"] for r in rel_rows]

        return EntityRow(
            id=entity_id,
            name=row["name"],
            type=row["type"],
            status=row["status"],
            fields=fields,
            aliases=aliases,
            related=related,
        )

    # -------------------------------------------------------------------------
    # Field operations
    # -------------------------------------------------------------------------

    def upsert_field(
        self,
        entity_id: int,
        field: str,
        value: str,
        source: str = "player_observed",
        confidence: str = "certain",
        turn_text: str | None = None,
    ) -> None:
        """Set a field value on an entity and record in the facts log."""
        now = self._now()
        self._upsert_field_internal(entity_id, field, value, source, confidence, turn_text, now)

        if field.lower() == "status":
            self._conn.execute(
                "UPDATE entities SET status = ?, updated_at = ? WHERE id = ?",
                (value, now, entity_id),
            )
        else:
            self._conn.execute(
                "UPDATE entities SET updated_at = ? WHERE id = ?",
                (now, entity_id),
            )

        self._conn.commit()

    def _upsert_field_internal(
        self,
        entity_id: int,
        field: str,
        value: str,
        source: str,
        confidence: str,
        turn_text: str | None,
        now: str,
    ) -> None:
        existing = self._conn.execute(
            "SELECT value FROM entity_fields WHERE entity_id = ? AND field = ?",
            (entity_id, field),
        ).fetchone()

        old_value = existing["value"] if existing else None

        self._conn.execute(
            """
            INSERT INTO entity_fields (entity_id, field, value)
            VALUES (?, ?, ?)
            ON CONFLICT(entity_id, field) DO UPDATE SET value = excluded.value
            """,
            (entity_id, field, value),
        )

        self._conn.execute(
            """
            INSERT INTO facts (entity_id, field, old_value, new_value, source, confidence, asserted_at, turn_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (entity_id, field, old_value, value, source, confidence, now, turn_text),
        )

    def get_field(self, entity_name: str, field: str) -> str | None:
        """Get the current value of a field for an entity by name."""
        row = self._conn.execute(
            """
            SELECT ef.value FROM entity_fields ef
            JOIN entities e ON e.id = ef.entity_id
            WHERE lower(e.name) = lower(?) AND ef.field = ?
            """,
            (entity_name, field),
        ).fetchone()
        return row["value"] if row else None

    # -------------------------------------------------------------------------
    # Aliases
    # -------------------------------------------------------------------------

    def insert_alias(self, entity_id: int, alias: str) -> None:
        """Add a name alias for an entity. Idempotent."""
        self._conn.execute(
            "INSERT OR IGNORE INTO aliases (entity_id, alias) VALUES (?, ?)",
            (entity_id, alias),
        )
        self._conn.commit()

    def resolve_alias(self, name: str) -> EntityRow | None:
        """Find an entity by name or alias."""
        return self.get_entity_by_name(name)

    # -------------------------------------------------------------------------
    # Relationships
    # -------------------------------------------------------------------------

    def insert_relationship(
        self,
        from_id: int,
        to_name: str,
        relation: str = "related to",
    ) -> None:
        """Insert a directed relationship. Idempotent."""
        self._conn.execute(
            """
            INSERT OR IGNORE INTO relationships (from_id, to_name, relation, asserted_at)
            VALUES (?, ?, ?, ?)
            """,
            (from_id, to_name, relation, self._now()),
        )
        self._conn.commit()

    def get_relationships(self, entity_id: int) -> list[dict]:
        """Get all outgoing relationships for an entity."""
        rows = self._conn.execute(
            "SELECT to_name, relation, asserted_at FROM relationships WHERE from_id = ?",
            (entity_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # History
    # -------------------------------------------------------------------------

    def insert_history(self, entity_id: int, note: str, recorded_at: str | None = None) -> None:
        """Append a timestamped history note to an entity."""
        self._conn.execute(
            "INSERT INTO entity_history (entity_id, note, recorded_at) VALUES (?, ?, ?)",
            (entity_id, note, recorded_at or self._now()),
        )
        self._conn.commit()

    def get_history(self, entity_id: int) -> list[dict]:
        """Get all history entries for an entity in chronological order."""
        rows = self._conn.execute(
            "SELECT note, recorded_at FROM entity_history WHERE entity_id = ? ORDER BY recorded_at",
            (entity_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # -------------------------------------------------------------------------
    # Conflict detection
    # -------------------------------------------------------------------------

    # Fields whose values are stable facts — contradicting them without an explicit
    # old_value still raises a conflict (e.g. role: captain → loadmaster).
    # Status-like progression fields (status, explored) are excluded because they
    # naturally advance and should never block a normal update.
    _STABLE_FIELDS = {"role", "category", "subtype", "position", "parent"}

    def detect_conflicts(self, updates: list[dict]) -> list[dict]:
        """
        Compare proposed updates against current DB state.
        Returns a list of conflict dicts for any update that contradicts what's recorded.

        Two cases raise a conflict:
        1. The player explicitly stated a prior value (old_value) that doesn't match DB.
        2. The update targets a stable field (role, category…) whose DB value is
           meaningful (not "unknown"/empty) and the new value contradicts it —
           even when no old_value was stated.
        """
        _PLACEHOLDER = {"unknown", "n/a", "none", ""}

        conflicts = []
        for update in updates:
            entity_name = update.get("entity", "")
            field = (update.get("field") or "").lower()
            old_value = update.get("old_value", "")
            new_value = update.get("new_value", "")

            if not (entity_name and field):
                continue

            current = self.get_field(entity_name, field)
            if current is None:
                continue  # Field doesn't exist yet — no conflict

            current_l = current.lower()
            new_l = new_value.lower() if new_value else ""

            # No conflict when re-stating the same fact
            if current_l == new_l:
                continue

            conflict = False

            # Case 1: explicit old_value that doesn't match DB
            if old_value and current_l != old_value.lower():
                conflict = True

            # Case 2: stable field with meaningful current value contradicted,
            # but only when the player did NOT correctly state the old value.
            # If old_value matches current, the player knows the current state
            # and is intentionally correcting it — that's valid, not a conflict.
            if (
                not conflict
                and field in self._STABLE_FIELDS
                and current_l not in _PLACEHOLDER
                and new_l not in _PLACEHOLDER
                and not (old_value and old_value.lower() == current_l)
            ):
                conflict = True

            if conflict:
                conflicts.append({
                    "entity": entity_name,
                    "field": field,
                    "db_value": current,
                    "proposed_value": new_value,
                    "old_value_expected": old_value,
                })

        return conflicts

    # -------------------------------------------------------------------------
    # Reflections
    # -------------------------------------------------------------------------

    def insert_reflection(self, category: str, note: str) -> None:
        self._conn.execute(
            "INSERT INTO reflections (category, note, created_at) VALUES (?, ?, ?)",
            (category, note, self._now()),
        )
        self._conn.commit()

    # -------------------------------------------------------------------------
    # Stats
    # -------------------------------------------------------------------------

    def get_stats(self) -> dict:
        entity_count = self._conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        relationship_count = self._conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        fact_count = self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        return {
            "entities": entity_count,
            "relationships": relationship_count,
            "facts": fact_count,
        }

    # -------------------------------------------------------------------------
    # Known entities (for extraction prompts)
    # -------------------------------------------------------------------------

    def get_known_entities(self) -> dict[str, list[str]]:
        """Return all entity names grouped by type, for use in extraction prompts."""
        rows = self._conn.execute(
            "SELECT name, type FROM entities ORDER BY type, name"
        ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            t = row["type"]
            result.setdefault(t, []).append(row["name"])
        return result
